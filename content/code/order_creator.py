"""
order_creator.py — the "Create Order" tab.

Maintains a persistent main list of ingredient nicknames (with optional
par levels) in whatever row order the user wants — typically the physical
walk-through order of the storage areas, seeded by loading a supplier
order guide file. For each list item it shows the latest price entry per
(supplier, product number) from cc.uni_g, auto-selects the lowest
normalized $/quant, lets the user override the supplier/item, and takes a
quick order quantity. Creating an order writes one combined xlsx (every
line, for internal record-keeping and "last order" tracking) plus one
separate file per supplier — each in that supplier's own chosen format
(xlsx or csv) and column selection, ready to send as-is. Clear Order, next
to Create Order, zeroes every quantity without touching the list, prices,
or last order -- a fresh start for building a different order.

Price options can be narrowed by self.max_age_months (0 = off): an option
older than the cutoff is hidden from the ingredient's price list *unless*
every option for that ingredient is stale, in which case the single most
recent one is kept anyway (an ingredient never ends up with zero options
just because nobody's re-priced it recently) -- and an option that
already has a quantity on it is always kept regardless of age, so
narrowing the cutoff can't make an in-progress order silently vanish from
view. This is a live view over the already-cached options (_visible_options,
applied in _push_rows), not a re-fetch -- changing it takes effect
immediately without hitting cc.uni_g again. A row's description also
picks up that entry's brand, comma-appended, when uni_g has one for it
("FLOUR AP 50LB, ACME") -- untouched when there isn't.

Price data flows one way, FROM cc.uni_g — this module never mutates
uni_g, costdf, or any cost method (findframe / cost_picker / get_cost_df
are read-only from here). Uploading new price lists is still the Order
Guide Reader tab's job; the upload widget here just drops files into
orders/ so they can be processed there, and "Load current prices"
re-reads uni_g afterwards.

Order quantities are entered per (ingredient, supplier/item) — an
ingredient can be split across suppliers (e.g. 3 cases from one, 2 from
another) in the same order. self.opt_quants holds this: nickname ->
{opt_id: quantity}. An ingredient's total order quantity is always the
sum of its option quantities; there's no separate top-level "selected
supplier" state to fall out of sync with it.

Files
    orders/order_list.xlsx                    main list + per-supplier export config
        sheet 'items':          nickname, par        (row order = list order)
        sheet 'export_config':  supplier, columns, format
    orders/created/order_all_<date>.xlsx       every created order, combined
        sheet 'all':            every line, always xlsx -- this is what
                                "last order" and the on-screen preview read back
    orders/created/order_<supplier>_<date>.xlsx|.csv
        one file per supplier, in that supplier's chosen format, with that
        supplier's configured columns/labels/order

Filenames carry the date only, not the time, so creating an order again
later the same day overwrites that day's files rather than piling up
timestamped duplicates — deliberately: fixing a quantity and re-creating
the order should replace what a supplier would actually receive, not
leave two conflicting versions sitting in the folder.

"Last order" is read from the newest orders/created/order_all_*.xlsx file
(the per-supplier files are excluded from that search — they're a subset
of the same data in a different shape, not a second source of truth).
"""

import os
import re
from datetime import datetime, timedelta

import pandas as pd
import ipywidgets as widgets
from IPython.display import display

from order_guide_reader import OrderGuideReader
from order_grid_widget import OrderGridWidget
from utils import _try_parse_size

ORDERS_DIR = 'orders'
CREATED_DIR = os.path.join(ORDERS_DIR, 'created')
LIST_FILE = os.path.join(ORDERS_DIR, 'order_list.xlsx')

# Columns every order line carries internally; per-supplier export config
# picks (and orders) a subset of these for the supplier sheets.
ORDER_LINE_COLUMNS = ['nickname', 'order quant', 'supplier', 'number',
                      'description', 'size', 'price', 'est total']
DEFAULT_EXPORT_COLS = ['number', 'description', 'size', 'order quant',
                       'price', 'est total']

_LEADING_NUM = re.compile(r'[-+]?\d*\.?\d+')
_WHOLE_FLOAT_RE = re.compile(r'^(-?\d+)\.0+$')


def _num(val, default=None):
    """float() that shrugs at '', None, NaN, '$1.23'."""
    if val is None:
        return default
    try:
        if isinstance(val, str):
            val = val.strip().lstrip('$')
            if not val:
                return default
        f = float(val)
        return f if f == f else default          # NaN check
    except (TypeError, ValueError):
        return default


def _clean_number_cell(val):
    """Product/item numbers should read as whole numbers -- 100923, not
    '100923.0' (a common artifact of pandas reading a numeric column that
    also has blank cells as float64, so the whole column upcasts to
    float). Returns a Python int when the value is purely numeric, so it
    writes into xlsx as a real number rather than text; alphanumeric SKUs
    and anything else are returned unchanged.
    """
    if val is None:
        return ''
    if isinstance(val, float):
        if val != val:                     # NaN
            return ''
        return int(val) if val == int(val) else val
    s = str(val).strip()
    if not s or s.lower() == 'nan':
        return ''
    m = _WHOLE_FLOAT_RE.match(s)
    if m:
        s = m.group(1)
    return int(s) if re.fullmatch(r'-?\d+', s) else s

def _case_price(price, unit, size_str):
    """Best-estimate dollar cost of ONE case/unit as ordered.

    For weight-priced items (order guide 'unit' == 'lb') the guide's
    'price' field is a $/lb *rate* -- CostCalculator and the Order Guide
    Reader both divide by exactly 1 lb when computing $/quantity for
    these rows, confirming 'price' is never a case total for them. Order
    Creator needs an actual per-case dollar figure to multiply by order
    quantity, so the rate gets multiplied by the case's nominal size
    (e.g. "40 lb") to estimate what one case will cost -- an estimate,
    since the exact billed weight isn't known until the case is weighed
    at delivery. Non-'lb' items' 'price' is already the case price as
    listed in the guide, so it's returned unchanged.
    """
    price = _num(price)
    if price is None:
        return None
    if isinstance(unit, str) and unit.strip().lower() == 'lb':
        size_q = _try_parse_size(size_str) if size_str else None
        if size_q is None:
            return None
        try:
            lbs = size_q.to('lb').magnitude
        except Exception:
            return None
        if lbs <= 0:
            return None
        return price * lbs
    return price

def _with_brand(description, brand):
    """Append a non-empty brand to the description, comma-separated --
    'FLOUR AP 50LB, ACME' -- leaving the description untouched when this
    particular row has no brand value (most won't)."""
    description = str(description or '').strip()
    brand = str(brand or '').strip()
    if not brand or brand.lower() == 'nan':
        return description
    return f"{description}, {brand}" if description else brand


def _parse_date(s):
    """'2026-07-01' -> a datetime, for comparing against an age cutoff.
    None for anything blank or not in that format (uni_g's own dates are
    always written this way, but a hand-edited or missing value shouldn't
    blow up the age filter -- it just can't be judged, so it's treated as
    unknown rather than as either recent or stale)."""
    s = str(s or '').strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d')
    except ValueError:
        return None


def _mark_low(opts):
    """Flag the cheapest (by normalized $/quantity, falling back to raw
    case price when that's not available) option in a list as 'low'.
    Mutates in place and always clears every other option's flag first,
    so calling this again on a re-ranked or filtered list -- e.g. once
    more in _push_rows after the age filter narrows what's visible --
    can't leave two options both flagged from an earlier pass."""
    for o in opts:
        o['low'] = False
    ranked = [o for o in opts if o.get('_per_val') is not None]
    pool = ranked if ranked else [o for o in opts if _num(o.get('price')) is not None]
    if not pool:
        return
    key = (lambda o: o['_per_val']) if ranked else (lambda o: _num(o['price']))
    min(pool, key=key)['low'] = True


def _parse_col_config(text):
    """'number:Item #, description, order quant:Qty' ->
    [('number','Item #'), ('description','description'), ('order quant','Qty')]
    A token with no ':' uses the field name itself as the label -- also how
    configs saved before renaming existed are read back."""
    cfg = []
    for token in str(text).split(','):
        token = token.strip()
        if not token:
            continue
        if ':' in token:
            field, label = token.split(':', 1)
            field, label = field.strip(), (label.strip() or field.strip())
        else:
            field = label = token
        cfg.append((field, label))
    return cfg


def _set_whole_number_format(worksheet, col_index_1based):
    """Explicit '0' (no-decimals) number format on a just-written column's
    data cells. Belt-and-suspenders alongside _clean_number_cell: guards
    against Excel's General format ever rendering a large numeric id in
    scientific notation, and keeps the column visually consistent even if
    a stray float slips through."""
    from openpyxl.utils import get_column_letter
    col_letter = get_column_letter(col_index_1based)
    for cell in worksheet[col_letter][1:]:      # [0] is the header row
        if isinstance(cell.value, (int, float)):
            cell.number_format = '0'


_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


def _safe_filename_part(supplier):
    """A supplier name, made safe to drop straight into a filename --
    strips/replaces characters the filesystem (or a zip/email attachment
    step later) would choke on. Blank supplier -> 'unassigned', matching
    the sheet-naming convention used elsewhere."""
    s = str(supplier or '').strip()
    if not s:
        return 'unassigned'
    s = _UNSAFE_FILENAME_CHARS.sub('_', s)
    return s.strip('_ ') or 'unassigned'


class OrderCreator:
    """UI + state for building supplier orders from the main ingredient list."""

    def __init__(self, cc=None, explorer=None):
        self.cc = cc
        self.explorer = explorer

        # ── state ────────────────────────────────────────────────────────
        self.items = []        # [{'nickname': str, 'par': float|None}] in list order
        self.opt_quants = {}    # nickname -> {opt_id: quantity} — order qty per supplier/item
        self.options = {}      # nickname -> [option dicts] from load_prices()
        self.last_order = {}   # nickname -> quant from most recent created order
        self.export_cols = {}  # supplier -> [(field, label), ...] for its sheet, in output order
        self.export_format = {}  # supplier -> 'xlsx' | 'csv'
        self._supplier_col_widgets = {}   # supplier -> Text widget
        self._supplier_format_widgets = {}  # supplier -> Dropdown widget
        self._clipboard = None  # [{'nickname','par'}, ...] cut from the list, or None
        self.max_age_months = 0  # 0 = no age filtering; see _visible_options

        os.makedirs(CREATED_DIR, exist_ok=True)
        self._load_list_file()
        self._load_last_order()
        self._setup_interface()

        if self.cc is not None and not getattr(self.cc, 'uni_g',
                                               pd.DataFrame()).empty:
            self.load_prices(quiet=True)
        self._push_rows()

    # ══════════════════════════════════════════════════════════════════════
    # price options
    # ══════════════════════════════════════════════════════════════════════

    def load_prices(self, button=None, quiet=False):
        """(Re)build the per-ingredient option lists from cc.uni_g.

        Read-only over the cost machinery: get_cost_df computes the
        comparable '$/quantity' exactly the way the guide display does
        (including per-row conversions), and _normalize_dollars_per_quantity
        re-expresses the whole column in one unit so a plain numeric sort
        is a valid "lowest price" ranking.

        The whole compute loop runs inside `with self.status_output:` so
        any stray print()s from that cost machinery (e.g. the "[conversion
        missing]" warning get_cost_df emits for an unconvertible unit) land
        in the log area instead of leaking into the raw cell output below
        the tab. Callers driving a multi-step operation (load a list, then
        prices) should clear self.status_output themselves right before
        calling this with quiet=True, then print their own follow-up
        message afterwards -- this method only clears on its own when it's
        the whole operation (quiet=False, i.e. a direct button click).
        """
        self.options = {}
        missing = []
        with self.status_output:
            if not quiet:
                self.status_output.clear_output()
            for item in self.items:
                nick = item['nickname']
                opts = self._compute_options(nick)
                self.options[nick] = opts
                if not opts:
                    missing.append(nick)
            self._rebuild_export_config_ui()
            self._push_rows()
            self.grid.all_nicknames = self._all_nicknames()
            if not quiet:
                n_opts = sum(len(v) for v in self.options.values())
                print(f"Loaded prices: {n_opts} options across "
                      f"{len(self.items)} ingredients.")
                if missing:
                    print(f"No price entries for {len(missing)}: "
                          + ', '.join(missing[:15])
                          + ('…' if len(missing) > 15 else ''))

    def _compute_options(self, nick):
        """Latest entry per (supplier, number) for one nickname, lowest
        normalized $/quant flagged. Returns [] when the guide has nothing.

        Keeps the internal '_per_val' field (the raw numeric $/quantity
        'low' was computed from) rather than stripping it -- _push_rows
        reuses it to re-flag 'low' among whatever survives the age filter,
        without having to re-parse the 'per_quant' display string back
        into a number. It's otherwise unused (the grid ignores it)."""
        if self.cc is None:
            return []
        try:
            df = self.cc.get_cost_df(nick)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        df = df.copy()

        # newest first, so drop_duplicates(keep='first') keeps latest prices
        if 'date' in df.columns:
            df = df.sort_values(by='date', ascending=False, ignore_index=True)

        # one common unit for the whole column -> leading float is sortable
        if ('$/quantity' in df.columns
                and hasattr(self.cc, '_normalize_dollars_per_quantity')):
            try:
                df['$/quantity'] = self.cc._normalize_dollars_per_quantity(
                    df['$/quantity'])
            except Exception:
                pass    # fall back to raw per-row strings; ranking uses price

        dedupe = [c for c in ('supplier', 'number') if c in df.columns]
        if not dedupe:
            dedupe = [c for c in ('description',) if c in df.columns]
        if dedupe:
            df = df.drop_duplicates(subset=dedupe, keep='first',
                                    ignore_index=True)

        opts = []
        for i, row in df.iterrows():
            per_str = str(row.get('$/quantity', '') or '')
            m = _LEADING_NUM.match(per_str.strip())
            per_val = float(m.group()) if m else None
            opt_id = row.get('_guide_index', i)
            try:
                opt_id = int(opt_id)
            except (TypeError, ValueError):
                opt_id = int(i)
            size_str = str(row.get('size', '') or '')
            unit_str = str(row.get('unit', '') or '')
            raw_price = row.get('price')
            opts.append({
                'opt_id': opt_id,
                'supplier': str(row.get('supplier', '') or ''),
                'number': _clean_number_cell(row.get('number', '')),
                'description': _with_brand(row.get('description', ''),
                                           row.get('brand', '')),
                'size': size_str,
                'unit': unit_str,
                'price': _num(raw_price, default=raw_price),
                'case_price': _case_price(raw_price, unit_str, size_str),
                'per_quant': per_str,
                'date': str(row.get('date', '') or ''),
                '_per_val': per_val,
                'low': False,
            })

        _mark_low(opts)
        # lowest first in the expanded view
        opts.sort(key=lambda o: (not o['low'],))
        return opts

    # ══════════════════════════════════════════════════════════════════════
    # grid
    # ══════════════════════════════════════════════════════════════════════

    def _push_rows(self):
        """Merge this order's in-progress quantities onto the current price
        options and hand the result to the grid. Called on every structural
        change (list edits, price reloads, order creation, the max-age
        filter changing); per-keystroke quantity/par edits are recorded
        straight into state by _on_grid_msg without a round trip back
        through here — see order_grid_widget's module docstring for why."""
        rows = []
        for item in self.items:
            nick = item['nickname']
            opt_quants = self.opt_quants.get(nick, {})
            visible = self._visible_options(nick, opt_quants)
            _mark_low(visible)   # re-rank "low" among what's actually shown

            opts = []
            total = 0.0
            for opt in visible:
                q = opt_quants.get(opt['opt_id'], 0) or 0
                total += q
                opt = dict(opt)
                opt['quant'] = q
                opts.append(opt)
            rows.append({
                'nickname': nick,
                'par': item.get('par'),
                'last': self.last_order.get(nick),
                'quant': total,
                'options': opts,
            })
        self.grid.rows = rows
        self.grid.title = 'Order list'

    def _visible_options(self, nick, opt_quants=None):
        """This ingredient's price options narrowed to self.max_age_months
        (0 = off, show everything) -- but never down to zero: if nothing
        qualifies as recent, fall back to just the single most recent
        option instead of hiding the ingredient's pricing entirely. An
        option that already has a quantity on it is always kept regardless
        of age, so filtering can never make an existing order silently
        disappear from view.
        """
        opts = self.options.get(nick, [])
        if not self.max_age_months or not opts:
            return list(opts)

        cutoff = datetime.now() - timedelta(days=30 * self.max_age_months)
        dated = [(o, _parse_date(o.get('date'))) for o in opts]
        recent = [o for o, d in dated if d is not None and d >= cutoff]

        if not recent:
            # nothing recent -- fall back to just the single most recent
            # option overall (or, if no date is parseable at all, don't
            # hide anything -- there's no basis to judge age on)
            with_dates = [(o, d) for o, d in dated if d is not None]
            recent = [max(with_dates, key=lambda pair: pair[1])[0]] if with_dates else list(opts)

        if opt_quants:
            visible_ids = {o['opt_id'] for o in recent}
            recent = recent + [o for o in opts
                               if o['opt_id'] not in visible_ids
                               and opt_quants.get(o['opt_id'], 0) > 0]
        return recent

    def _on_max_age_change(self, change):
        """The age cutoff is a view over the already-cached self.options,
        not something that requires re-fetching from cc.uni_g -- so
        changing it just re-pushes rows with the new cutoff applied,
        instantly, without re-running load_prices (and without risking
        another round of conversion-missing warnings for ingredients that
        already triggered one)."""
        self.max_age_months = change['new'] or 0
        self._push_rows()

    def _on_grid_msg(self, widget, content, buffers):
        mtype = content.get('type')
        nick = content.get('nickname')
        if mtype == 'opt_quant':
            opt_id = content.get('opt_id')
            v = _num(content.get('value'), default=0) or 0
            bucket = self.opt_quants.setdefault(nick, {})
            if v > 0:
                bucket[opt_id] = v
            else:
                bucket.pop(opt_id, None)
                if not bucket:
                    self.opt_quants.pop(nick, None)
        elif mtype == 'par':
            for item in self.items:
                if item['nickname'] == nick:
                    item['par'] = _num(content.get('value'))
                    break
        elif mtype == 'insert':
            self._insert_ingredient(content.get('nickname'),
                                    content.get('before_nickname'))
        elif mtype == 'selection_action':
            action = content.get('action')
            if action == 'cut':
                self._cut_items(content.get('nicknames') or [])
            elif action == 'paste':
                self._paste_items(content.get('before_nickname'))

    def _item_index_before(self, before_nickname):
        """List position to insert at: right before `before_nickname`, or
        the end of the list if it's None or not found (e.g. the bottom
        '+ Add ingredient' row, which has no nickname to anchor to)."""
        if before_nickname is not None:
            for j, it in enumerate(self.items):
                if it['nickname'] == before_nickname:
                    return j
        return len(self.items)

    def _insert_ingredient(self, nick, before_nickname):
        """Add one ingredient at a specific spot in the list -- the
        kernel-side half of the grid's inline "Add here" row (replaces the
        old standalone add-nickname box)."""
        nick = (nick or '').strip()
        if not nick:
            return
        if any(i['nickname'] == nick for i in self.items):
            with self.status_output:
                self.status_output.clear_output()
                print(f"'{nick}' is already on the list.")
            self._push_rows()   # redraw so the browser closes its add-input
            return
        self.items.insert(self._item_index_before(before_nickname),
                          {'nickname': nick, 'par': None})
        with self.status_output:
            self.status_output.clear_output()
            if nick not in self.options:
                self.options[nick] = self._compute_options(nick)
        self._rebuild_export_config_ui()
        self._push_rows()

    def _cut_items(self, nicknames):
        """Remove the given nicknames from the list into an in-memory
        clipboard (par preserved; cached price options and any in-progress
        order quantities are left alone, keyed by nickname, so pasting the
        same item back restores them for free)."""
        wanted = set(nicknames)
        if not wanted:
            return
        cut = [i for i in self.items if i['nickname'] in wanted]
        if not cut:
            return
        self.items = [i for i in self.items if i['nickname'] not in wanted]
        self._clipboard = cut
        self.grid.has_clipboard = True
        self.grid.clipboard_count = len(cut)
        self._push_rows()

    def _paste_items(self, before_nickname):
        """Insert the cut clipboard's items just before `before_nickname`
        (or at the end, for the bottom add row). A nickname already
        elsewhere in the list is skipped rather than duplicated. Single-use,
        like a normal cut/paste clipboard -- cleared once pasted."""
        if not self._clipboard:
            return
        existing = {i['nickname'] for i in self.items}
        idx = self._item_index_before(before_nickname)

        to_compute, skipped = [], []
        for entry in self._clipboard:
            nick = entry['nickname']
            if nick in existing:
                skipped.append(nick)
                continue
            self.items.insert(idx, dict(entry))
            idx += 1
            existing.add(nick)
            if nick not in self.options:
                to_compute.append(nick)

        with self.status_output:
            self.status_output.clear_output()
            for nick in to_compute:
                self.options[nick] = self._compute_options(nick)
            if skipped:
                print("Already on the list, skipped: " + ', '.join(skipped))

        self._clipboard = None
        self.grid.has_clipboard = False
        self.grid.clipboard_count = 0
        self._rebuild_export_config_ui()
        self._push_rows()

    # ══════════════════════════════════════════════════════════════════════
    # main list management
    # ══════════════════════════════════════════════════════════════════════

    def load_list_from_guide_file(self, button=None):
        """Seed the main list from a supplier order guide/confirmation file
        — the file's row order becomes the list order (physical location).
        Existing pars are kept for nicknames that survive the reload."""
        path = self.guide_file_dropdown.value
        if not path or path == 'No order files found':
            with self.status_output:
                self.status_output.clear_output()
                print("No order file selected.")
            return
        with self.status_output:
            self.status_output.clear_output()
            try:
                reader = OrderGuideReader(cc=self.cc)
                reader.file_type = None
                df = reader.read_order_file(path)
            except Exception as e:
                print(f"Error reading '{path}': {e}")
                import traceback
                traceback.print_exc()
                return

            old_pars = {i['nickname']: i.get('par') for i in self.items}
            seen, items = set(), []
            skipped = 0
            for nick in df.get('nickname', pd.Series(dtype=object)):
                if pd.isna(nick) or not str(nick).strip():
                    skipped += 1
                    continue
                nick = str(nick).strip()
                if nick in seen:
                    continue
                seen.add(nick)
                items.append({'nickname': nick, 'par': old_pars.get(nick)})
            self.items = items
            print(f"Loaded {len(items)} ingredients from '{os.path.basename(path)}' "
                  f"(file order preserved).")
            if skipped:
                print(f"Skipped {skipped} rows without a nickname — assign "
                      f"nicknames in the Order Guide Reader tab to include them.")
        self.load_prices(quiet=True)
        self._push_rows()

    def build_list_from_database(self, button=None):
        """Main list = every nickname currently in the guide, in uni_g order."""
        if self.cc is None or getattr(self.cc, 'uni_g', pd.DataFrame()).empty:
            with self.status_output:
                self.status_output.clear_output()
                print("No database loaded.")
            return
        old_pars = {i['nickname']: i.get('par') for i in self.items}
        seen, items = set(), []
        for nick in self.cc.uni_g['nickname'].dropna():
            nick = str(nick).strip()
            if not nick or nick in seen:
                continue
            seen.add(nick)
            items.append({'nickname': nick, 'par': old_pars.get(nick)})
        self.items = items
        with self.status_output:
            self.status_output.clear_output()
            print(f"Built list of {len(items)} ingredients from the database.")
        self.load_prices(quiet=True)
        self._push_rows()

    def _all_nicknames(self):
        if self.cc is None or getattr(self.cc, 'uni_g', pd.DataFrame()).empty:
            return []
        return sorted(set(str(n) for n in
                          self.cc.uni_g['nickname'].dropna().unique()))

    # ── persistence: main list + export config ──────────────────────────

    def save_list(self, button=None):
        self._read_export_config_ui()
        items_df = pd.DataFrame(
            [{'nickname': i['nickname'], 'par': i.get('par')}
             for i in self.items],
            columns=['nickname', 'par'])
        cfg_df = pd.DataFrame(
            [{'supplier': s,
              'columns': ','.join(f"{f}:{l}" for f, l in cols),
              'format': self.export_format.get(s, 'xlsx')}
             for s, cols in self.export_cols.items()],
            columns=['supplier', 'columns', 'format'])
        with self.status_output:
            self.status_output.clear_output()
            try:
                with pd.ExcelWriter(LIST_FILE, engine='openpyxl') as xw:
                    items_df.to_excel(xw, sheet_name='items', index=False)
                    cfg_df.to_excel(xw, sheet_name='export_config', index=False)
                print(f"Saved list ({len(items_df)} items) and supplier "
                      f"output columns/format to '{LIST_FILE}'.")
            except Exception as e:
                print(f"Error saving list: {e}")

    def _load_list_file(self):
        if not os.path.exists(LIST_FILE):
            return
        try:
            sheets = pd.read_excel(LIST_FILE, sheet_name=None)
        except Exception:
            return
        items_df = sheets.get('items')
        if items_df is not None and 'nickname' in items_df.columns:
            self.items = [
                {'nickname': str(r['nickname']).strip(),
                 'par': _num(r.get('par'))}
                for _, r in items_df.iterrows()
                if pd.notna(r['nickname']) and str(r['nickname']).strip()
            ]
        cfg_df = sheets.get('export_config')
        if cfg_df is not None and {'supplier', 'columns'} <= set(cfg_df.columns):
            for _, r in cfg_df.iterrows():
                if pd.isna(r['supplier']):
                    continue
                supplier = str(r['supplier']).strip()
                # _parse_col_config also reads pre-renaming configs saved
                # as plain "field,field,..." (no colon -> label == field).
                cfg = _parse_col_config(r['columns'])
                if cfg:
                    self.export_cols[supplier] = cfg
                if 'format' in cfg_df.columns and pd.notna(r.get('format')):
                    fmt = str(r['format']).strip().lower()
                    if fmt in ('xlsx', 'csv'):
                        self.export_format[supplier] = fmt

    # ══════════════════════════════════════════════════════════════════════
    # last order
    # ══════════════════════════════════════════════════════════════════════

    def _latest_created_file(self):
        """Newest combined order file -- order_all_<date>.xlsx specifically,
        not the per-supplier files sitting alongside it (those are a
        reshaped subset of the same data, not a second source of truth).
        """
        try:
            files = [os.path.join(CREATED_DIR, f)
                     for f in os.listdir(CREATED_DIR)
                     if f.lower().startswith('order_all_')
                     and f.lower().endswith('.xlsx')]
        except FileNotFoundError:
            return None
        # order_all_<YYYY-MM-DD>.xlsx sorts chronologically by name (one
        # file per date, same-day re-creates overwrite rather than adding
        # a second one, so there's no same-date ambiguity to worry about).
        return max(files) if files else None

    def _load_last_order(self):
        self.last_order = {}
        path = self._latest_created_file()
        if not path:
            return
        try:
            df = pd.read_excel(path, sheet_name='all')
        except Exception:
            return
        if {'nickname', 'order quant'} <= set(df.columns):
            for _, r in df.iterrows():
                q = _num(r['order quant'])
                if pd.notna(r['nickname']) and q:
                    # sum, not overwrite -- a split order has one line per
                    # supplier/item, so the same nickname can repeat.
                    nick = str(r['nickname'])
                    self.last_order[nick] = self.last_order.get(nick, 0) + q

    def show_last_order(self, button=None):
        path = self._latest_created_file()
        with self.order_output:
            self.order_output.clear_output()
            if not path:
                print("No created orders yet.")
                return
            print(f"Last order: {os.path.basename(path)}")
            try:
                odf = pd.read_excel(path, sheet_name='all')
            except Exception as e:
                print(f"Error reading '{path}': {e}")
                return
            # Re-derive the same per-supplier view create_order's own
            # preview shows, using whatever export_cols/format config is
            # current now -- not necessarily what was configured back when
            # this order was actually created, but that's the useful
            # question to answer ("what would today's settings produce").
            if 'supplier' in odf.columns:
                for supplier, sdf in odf.groupby('supplier', sort=False):
                    out_df, _ = self._supplier_export_frame(sdf, supplier)
                    display(widgets.HTML(
                        f"<h4 style='margin:8px 0 2px'>"
                        f"{supplier or 'unassigned'} — {len(sdf)} lines</h4>"))
                    display(out_df.reset_index(drop=True))
            display(widgets.HTML("<h4 style='margin:8px 0 2px'>all</h4>"))
            display(odf)

    # ══════════════════════════════════════════════════════════════════════
    # create order
    # ══════════════════════════════════════════════════════════════════════

    def _supplier_export_frame(self, sdf, supplier):
        """This supplier's lines restricted, reordered, and renamed per
        self.export_cols. Falls back to the default column set (field names
        used as their own labels) if nothing's configured or nothing in the
        configured list actually matches sdf's columns.

        Returns (renamed_dataframe, source_field_order) -- the second value
        lets the caller still locate a field like 'number' positionally
        after the rename, to apply whole-number formatting to it.
        """
        cfg = self.export_cols.get(supplier) or [(f, f) for f in DEFAULT_EXPORT_COLS]
        cfg = [(f, l) for f, l in cfg if f in sdf.columns]
        if not cfg:
            cfg = [(f, f) for f in sdf.columns]
        fields = [f for f, _ in cfg]
        labels = [l for _, l in cfg]
        out_df = sdf[fields].copy()
        out_df.columns = labels
        return out_df, fields

    def clear_order(self, button=None):
        """Zero out every order quantity -- both the per-option quantities
        and the main-box rollups derived from them -- without touching the
        list, prices, or last order. A fresh start when building a
        different order from scratch rather than adjusting the current
        one; nothing here is written to disk until Create Order runs."""
        with self.status_output:
            self.status_output.clear_output()
            if not self.opt_quants:
                print("Nothing to clear — no quantities are currently set.")
                return
            self.opt_quants = {}
            self._push_rows()
            print("Cleared all order quantities.")

    def create_order(self, button=None):
        """Write the order files: one combined order_all_<date>.xlsx (the
        record 'last order' and the preview below read back) plus one
        order_<supplier>_<date> file per supplier, in that supplier's own
        chosen format and column selection. Filenames carry the date only
        -- re-running this later the same day overwrites that day's files
        rather than adding new ones. This only creates output -- it
        doesn't touch self.opt_quants or self.last_order, so the entry
        list and the 'last' column stay exactly as they were; re-run this
        as many times as needed (e.g. after nudging a quantity) without
        losing anything.
        """
        self._read_export_config_ui()
        lines = []
        for item in self.items:            # preserve list (physical) order
            nick = item['nickname']
            opt_quants = self.opt_quants.get(nick)
            if not opt_quants:
                continue
            # stable order: whatever order load_prices ranked the options in
            for opt in self.options.get(nick, []):
                q = opt_quants.get(opt['opt_id'], 0)
                if not q or q <= 0:
                    continue
                price = _num(opt['price'])
                case_price = opt.get('case_price')
                if case_price is None:
                    case_price = price
                lines.append({
                    'nickname': nick,
                    'order quant': q,
                    'supplier': opt['supplier'],
                    'number': opt['number'],
                    'description': opt['description'],
                    'size': opt['size'],
                    'price': price if price is not None else opt['price'],
                    'est total': round(q * case_price, 2) if case_price is not None else '',
                })

        with self.status_output:
            self.status_output.clear_output()
            if not lines:
                print("Nothing to order — enter a quantity for at least "
                      "one ingredient/supplier.")
                return

            odf = pd.DataFrame(lines, columns=ORDER_LINE_COLUMNS)
            stamp = datetime.now().strftime('%Y-%m-%d')
            written = []
            try:
                # combined record -- always xlsx, always the raw column
                # names, regardless of any supplier's csv/rename choices
                combined_path = os.path.join(
                    CREATED_DIR, f'order_all_{stamp}.xlsx')
                with pd.ExcelWriter(combined_path, engine='openpyxl') as xw:
                    odf.to_excel(xw, sheet_name='all', index=False)
                    if 'number' in odf.columns:
                        _set_whole_number_format(
                            xw.sheets['all'],
                            list(odf.columns).index('number') + 1)
                written.append(combined_path)

                # one separate file per supplier, in that supplier's
                # own chosen format (xlsx or csv)
                for supplier, sdf in odf.groupby('supplier', sort=False):
                    out_df, fields = self._supplier_export_frame(sdf, supplier)
                    fmt = self.export_format.get(supplier, 'xlsx')
                    safe_name = _safe_filename_part(supplier)

                    if fmt == 'csv':
                        path = os.path.join(
                            CREATED_DIR, f'order_{safe_name}_{stamp}.csv')
                        out_df.to_csv(path, index=False)
                    else:
                        path = os.path.join(
                            CREATED_DIR, f'order_{safe_name}_{stamp}.xlsx')
                        sheet = safe_name[:31]
                        with pd.ExcelWriter(path, engine='openpyxl') as xw:
                            out_df.to_excel(xw, sheet_name=sheet, index=False)
                            if 'number' in fields:
                                _set_whole_number_format(
                                    xw.sheets[sheet], fields.index('number') + 1)
                    written.append(path)

                print(f"Created order with {len(odf)} lines across "
                      f"{len(written)} file(s):")
                for p in written:
                    print(f"  {p}")

                totals = odf.groupby('supplier')['est total'].apply(
                    lambda s: pd.to_numeric(s, errors='coerce').sum())
                for supplier, tot in totals.items():
                    print(f"  {supplier or 'unassigned'}: "
                          f"{(odf['supplier'] == supplier).sum()} lines, "
                          f"est ${tot:,.2f}")
            except Exception as e:
                print(f"Error writing order: {e}")
                import traceback
                traceback.print_exc()
                return

        # show the per-supplier breakdown -- order list & quantities are
        # untouched, so the grid still shows exactly what was just written
        with self.order_output:
            self.order_output.clear_output()
            for supplier, sdf in odf.groupby('supplier', sort=False):
                out_df, _ = self._supplier_export_frame(sdf, supplier)
                fmt = self.export_format.get(supplier, 'xlsx')
                display(widgets.HTML(
                    f"<h4 style='margin:8px 0 2px'>"
                    f"{supplier or 'unassigned'} ({fmt}) — {len(sdf)} lines</h4>"))
                display(out_df.reset_index(drop=True))

    # ── export column config (per supplier) ──────────────────────────────

    def _rebuild_export_config_ui(self):
        """One row per supplier seen in the current options: a Text input
        for 'field:Custom Label' pairs, comma-separated, in output order --
        the field selects the data, the label is what ends up as that
        supplier's file's column header (omit ':Label' to keep the field's
        own name) -- plus a format Dropdown choosing xlsx or csv for that
        supplier's own output file.

        Reads any in-progress edits in the existing widgets into
        self.export_cols/export_format first, so rebuilding (e.g. after
        adding an ingredient or reloading prices) can't silently discard a
        rename or format choice the user made but hasn't saved yet.
        """
        self._read_export_config_ui()
        suppliers = sorted({o['supplier']
                            for opts in self.options.values()
                            for o in opts if o['supplier']})
        for s in suppliers:
            self.export_cols.setdefault(s, [(f, f) for f in DEFAULT_EXPORT_COLS])
            self.export_format.setdefault(s, 'xlsx')
        rows = []
        self._supplier_col_widgets = {}
        self._supplier_format_widgets = {}
        for s in suppliers:
            t = widgets.Text(
                value=', '.join(f"{f}:{l}" for f, l in self.export_cols[s]),
                description=f'{s}:',
                layout=widgets.Layout(width='500px'),
                style={'description_width': '60px'})
            fmt_dd = widgets.Dropdown(
                options=['xlsx', 'csv'],
                value=self.export_format[s],
                layout=widgets.Layout(width='90px'))
            self._supplier_col_widgets[s] = t
            self._supplier_format_widgets[s] = fmt_dd
            rows.append(widgets.HBox([t, fmt_dd]))
        hint = widgets.HTML(
            "<span style='font-size:12px;color:var(--mv-muted,#66727f)'>"
            "Columns per supplier file: <code>field:Custom Label</code>, "
            "comma-separated, in output order (<code>:Label</code> is "
            "optional -- omit it to keep the field's own name), plus that "
            "supplier's own output format. "
            "Available fields: " + ', '.join(ORDER_LINE_COLUMNS) + ". "
            "Saved together with the list via 💾 Save list.</span>")
        self.export_config_box.children = tuple([hint] + rows)

    def _read_export_config_ui(self):
        for s, t in self._supplier_col_widgets.items():
            cfg = _parse_col_config(t.value)
            if cfg:
                self.export_cols[s] = cfg
        for s, dd in self._supplier_format_widgets.items():
            self.export_format[s] = dd.value

    # ══════════════════════════════════════════════════════════════════════
    # uploads / files
    # ══════════════════════════════════════════════════════════════════════

    def get_order_files(self):
        if not os.path.exists(ORDERS_DIR):
            os.makedirs(ORDERS_DIR)
        files = [f for f in os.listdir(ORDERS_DIR)
                 if f.lower().endswith(('.xls', '.xlsx', '.csv'))]
        paths = [os.path.join(ORDERS_DIR, f) for f in sorted(files)]
        return paths if paths else ['No order files found']

    def refresh_files(self, button=None):
        self.guide_file_dropdown.options = self.get_order_files()

    def on_file_upload(self, change):
        """Save an uploaded guide/price-list file into orders/. Handles both
        FileUpload return shapes (dict in classic Jupyter, tuple/list of
        objects in JupyterLite) — same pattern as menu_viewer.on_file_upload."""
        if not change['new']:
            return
        uploaded = change['new']
        saved = []
        try:
            if isinstance(uploaded, dict):
                for _, fdata in uploaded.items():
                    name = fdata['metadata']['name']
                    content = fdata['content']
                    saved.append(self._save_upload(name, content))
            else:
                for fobj in uploaded:
                    saved.append(self._save_upload(fobj.name, fobj.content))
        except Exception as e:
            with self.status_output:
                self.status_output.clear_output()
                print(f"Error saving upload: {e}")
            return
        self.refresh_files()
        with self.status_output:
            self.status_output.clear_output()
            for p in saved:
                print(f"Saved '{p}'.")
            print("To update prices in the database, process it in the "
                  "Order Guide Reader tab, then click 'Load current prices' "
                  "here.")

    def _save_upload(self, name, content):
        path = os.path.join(ORDERS_DIR, os.path.basename(name))
        with open(path, 'wb') as f:
            f.write(bytes(content))
        return path

    # ══════════════════════════════════════════════════════════════════════
    # interface
    # ══════════════════════════════════════════════════════════════════════

    def _setup_interface(self):
        # ── main list management row ─────────────────────────────────────
        self.guide_file_dropdown = widgets.Dropdown(
            options=self.get_order_files(), description='Order file:',
            layout=widgets.Layout(width='350px'))
        self.refresh_button = widgets.Button(
            description='🔄 Refresh', tooltip='Refresh file list',
            layout=widgets.Layout(width='100px'))
        self.refresh_button.on_click(self.refresh_files)
        self.load_list_button = widgets.Button(
            description='Load list from file', button_style='primary',
            tooltip="Main list = this file's items, in file order",
            layout=widgets.Layout(width='160px'))
        self.load_list_button.on_click(self.load_list_from_guide_file)
        self.db_list_button = widgets.Button(
            description='List from database',
            tooltip='Main list = every guide nickname',
            layout=widgets.Layout(width='160px'))
        self.db_list_button.on_click(self.build_list_from_database)
        self.save_list_button = widgets.Button(
            description='💾 Save list', button_style='success',
            tooltip=f'Save list + export config to {LIST_FILE}',
            layout=widgets.Layout(width='120px'))
        self.save_list_button.on_click(self.save_list)

        # ── prices / last order row ──────────────────────────────────────
        self.upload_widget = widgets.FileUpload(
            accept='.xls,.xlsx,.csv', multiple=False,
            description='Upload price list',
            layout=widgets.Layout(width='190px'))
        self.upload_widget.observe(self.on_file_upload, names='value')
        self.load_prices_button = widgets.Button(
            description='Load current prices', button_style='primary',
            tooltip='Rebuild supplier options from the current database',
            layout=widgets.Layout(width='170px'))
        self.load_prices_button.on_click(self.load_prices)
        self.last_order_button = widgets.Button(
            description='Show last order',
            layout=widgets.Layout(width='140px'))
        self.last_order_button.on_click(self.show_last_order)
        self.max_age_input = widgets.BoundedIntText(
            value=self.max_age_months, min=0, max=60,
            description='Max age (mo):',
            tooltip='Hide price options older than this many months '
                    '(0 = show everything). An ingredient with nothing '
                    'recent still shows its single most recent price, and '
                    'an option you\'ve already put a quantity on is never '
                    'hidden.',
            layout=widgets.Layout(width='170px'),
            style={'description_width': '90px'})
        self.max_age_input.observe(self._on_max_age_change, names='value')

        # ── grid ─────────────────────────────────────────────────────────
        # Adding an ingredient now happens inline in the grid itself (its
        # own "+ Add ingredient" row / a row's ⋯ menu -> "Add here"), so
        # there's no separate add-nickname box up here anymore.
        self.grid = OrderGridWidget()
        self.grid.all_nicknames = self._all_nicknames()
        self.grid.has_clipboard = False
        self.grid.clipboard_count = 0
        self.grid.on_msg(self._on_grid_msg)

        # ── create order + export config ─────────────────────────────────
        self.create_button = widgets.Button(
            description='Create Order', button_style='success',
            tooltip='Write the order file and split by supplier',
            layout=widgets.Layout(width='150px'))
        self.create_button.on_click(self.create_order)
        self.clear_order_button = widgets.Button(
            description='Clear Order', button_style='warning',
            tooltip='Zero out every order quantity (the list, prices, '
                    'and last order are left untouched)',
            layout=widgets.Layout(width='150px'))
        self.clear_order_button.on_click(self.clear_order)
        self.export_config_box = widgets.VBox([])
        self.export_accordion = widgets.Accordion(
            children=[self.export_config_box], selected_index=None)
        self.export_accordion.set_title(0, 'Supplier output columns')
        self._rebuild_export_config_ui()

        self.status_output = widgets.Output()
        self.order_output = widgets.Output()

        self.container = widgets.VBox([
            widgets.HTML(value="<h3>Create Order</h3>"),
            widgets.HBox([self.guide_file_dropdown, self.refresh_button,
                          self.load_list_button, self.db_list_button,
                          self.save_list_button]),
            widgets.HBox([self.upload_widget, self.load_prices_button,
                          self.last_order_button, self.max_age_input]),
            self.grid,
            widgets.HBox([self.create_button, self.clear_order_button]),
            self.export_accordion,
            self.status_output,
            self.order_output,
        ])

    def display(self):
        display(self.container)
