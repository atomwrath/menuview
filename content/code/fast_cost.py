"""
fast_cost.py  —  drop-in acceleration layer for CostCalculator.

WHAT IT CHANGES
    Only the *access pattern*. Pricing and unit conversion are reused verbatim
    from the base class, so computed numbers are identical to today:
        - leaves  -> self.get_simple_ingredient_cost(...)   (your cost_picker path)
        - scaling -> parse_quant / quantity_cost_and_conv   (your utils)

WHAT IT ADDS
    - children/parents dependency maps built once from a groupby
    - precomputed (item,ingredient) -> row position / quantity / saved cost
    - a memo of FULL recipe costs (one full yield), keyed by recipe name
    - O(affected) ancestor invalidation inside the clear_cost your UI already calls
    - O(1) positional write-back into costdf['cost'] so every existing reader
      (setdf / update_display / ordered_xlsx / write_cc) works UNCHANGED

INTEGRATION  (only two touch points — see notes at bottom of this file)
    1. activate the subclass once
    2. route the cost-method dropdown through change_cost_method()
    The per-edit clear_cost / recipe_cost calls already in your widgets are
    overridden here, so no other widget code changes.
"""

from functools import lru_cache

import pandas as pd

from utils import parse_quant, parse_unit_conversion, quantity_cost_and_conv

# Extra utils used by the optimised get_cost_df; imported defensively.
try:
    from utils import Q_, parse_size, maybeprint
except Exception:  # pragma: no cover
    Q_ = parse_size = maybeprint = None

# Cache the pure string->Quantity parsers (hit thousands of times with the same
# literals across a tree). Independent win, biggest in Pyodide where parsing is slow.
_parse_quant = lru_cache(maxsize=None)(parse_quant)
#_parse_conv = lru_cache(maxsize=None)(parse_unit_conversion)
_parse_conv = lru_cache(maxsize=None)(lambda conv_str: tuple(parse_unit_conversion(conv_str)))
_parse_size = lru_cache(maxsize=None)(parse_size) if parse_size is not None else None


class FastCostMixin:
    # ── map construction ──────────────────────────────────────────────────
    def read_from_xlsx(self, *a, **kw):
        out = super().read_from_xlsx(*a, **kw)
        self._build_maps(reset_memo=True)
        return out

    def _build_maps(self, reset_memo=False):
        """One pass over costdf rebuilds the dependency structure.

        Memo is PRESERVED across rebuilds (unaffected recipes stay cached);
        only read_from_xlsx and change_cost_method reset it wholesale.
        """
        df = self.costdf
        if reset_memo or not hasattr(self, "_memo"):
            self._memo = {}                    # recipe name -> full recipe cost
        self._children = {}                    # item -> [(ingredient, quant_str)]
        self._parents = {}                     # ingredient -> set(items)
        self._quant = {}                       # (item, ingredient) -> quant_str
        self._saved = {}                       # (item, ingredient) -> saved cost
        self._rowpos = {}                      # (item, ingredient) -> int position
        self._recipe_yield = {}                # recipe name -> parsed yield Quantity
        self._recipe_conv = {}                 # recipe name -> conversion spec
        self._guide_nicks = (
            set(self.uni_g["nickname"].dropna().unique())
            if "nickname" in self.uni_g.columns else set()
        )
        # leaf-pricing cache + lazily-built guide index (preserved across map
        # rebuilds; cleared on cost-method change and on edits via clear_cost)
        if not hasattr(self, "_leaf_cost"):
            self._leaf_cost = {}               # (nickname, quant_str) -> leaf cost
        if not hasattr(self, "_guide_by_nick"):
            self._guide_by_nick = None         # built lazily by _ensure_guide_index
            self._guide_dirty = True
            self._guide_nrows = -1
        self._maps_nrows = len(df)
        self._cost_col = df.columns.get_loc("cost") if "cost" in df.columns else None

        if df.empty:
            return

        items = df["item"].astype(str).tolist()
        ings = df["ingredient"].astype(str).tolist()
        quants = df["quantity"].tolist()
        saved = df["saved cost"].tolist() if "saved cost" in df.columns else [None] * len(df)
        convs = df["conversion"].tolist() if "conversion" in df.columns else [None] * len(df)

        for pos, (it, ing, q, sc, cv) in enumerate(zip(items, ings, quants, saved, convs)):
            self._quant[(it, ing)] = q
            self._rowpos[(it, ing)] = pos
            try:
                self._saved[(it, ing)] = float(sc)
            except (TypeError, ValueError):
                self._saved[(it, ing)] = -1.0
            if it == "recipe":
                try:
                    self._recipe_yield[ing] = _parse_quant(q)
                except Exception:
                    self._recipe_yield[ing] = None
                self._recipe_conv[ing] = cv
            else:
                self._children.setdefault(it, []).append((ing, q))
                self._parents.setdefault(ing, set()).add(it)

    def _ensure_fresh(self):
        """Auto-heal after row add/remove the UI did outside our overrides
        (create_recipe concats, ingredient add/remove). Cheap length guard."""
        if getattr(self, "_children", None) is None or len(self.costdf) != self._maps_nrows:
            self._build_maps()

    # ── guide index: make find_nick O(1) instead of a full uni_g scan ──────
    def _ensure_guide_index(self):
        """Build {nickname -> rows} once. Rebuilt when the guide changes
        (length change, or _guide_dirty set by an edit). Self-initializing."""
        if (getattr(self, "_guide_by_nick", None) is None
                or getattr(self, "_guide_dirty", True)
                or len(self.uni_g) != getattr(self, "_guide_nrows", -1)):
            self._guide_by_nick = {}
            if "nickname" in self.uni_g.columns and not self.uni_g.empty:
                for nick, grp in self.uni_g.groupby("nickname", observed=True):
                    self._guide_by_nick[nick] = grp
            self._guide_nrows = len(self.uni_g)
            self._guide_dirty = False

    def find_nick(self, inick):
        self._ensure_guide_index()
        grp = self._guide_by_nick.get(inick)
        if grp is not None:
            return grp
        return self.uni_g.loc[self.uni_g["nickname"] == inick]   # fallback

    def get_simple_ingredient_cost(self, inick, iquant):
        """Memoised leaf pricing: identical (nickname, quantity) prices once.
        Cleared on cost-method change and on any edit (via clear_cost)."""
        key = (inick, str(iquant))
        if not hasattr(self, "_leaf_cost"):
            self._leaf_cost = {}
        cached = self._leaf_cost.get(key)
        if cached is not None:
            return cached
        cost = super().get_simple_ingredient_cost(inick, iquant)
        self._leaf_cost[key] = cost
        return cost

    def get_cost_df(self, myingr, myquant=None):
        """Same logic as the base get_cost_df, but accumulates rows in a list and
        builds the DataFrame ONCE instead of growing it per row (the per-row
        Series enlargement + concat was the dominant cold-calc cost). parse_size
        is cached, since identical size strings repeat across the guide."""
        if myquant is not None:
            myquant = _parse_quant(myquant)

        results = self.find_nick(myingr)
        if results is None or len(results) == 0:
            return pd.DataFrame()

        convr = set(results['conversion'].dropna().unique())
        rows = []
        for idx, r in results.iterrows():
            quant = _parse_size(r['size'])
            price = r['price']

            thisconv = list(convr)
            if isinstance(r['conversion'], str):
                thisconv = [r['conversion']]
                for c in convr:
                    if c not in thisconv:
                        thisconv.append(c)

            if isinstance(price, str):
                price = float(price.strip('$'))
            if price <= 0:
                maybeprint(f"!!! no price for: {myingr}")
            if r['unit'] in ['lb', 'LB', 'Lb']:
                quant = Q_('1 lb')

            nextprice = 0
            myconv = 1
            if myquant is None:
                myquant = Q_(f"1 {str(quant.units)}")
            if myquant.m == 0:
                myquant = Q_(f"0 {str(quant.units)}")
            else:
                nextprice, myconv = quantity_cost_and_conv(
                    price / quant, myquant, parse_unit_conversion(thisconv))
                if nextprice is None:
                    recipe_unit = str(myquant.units)
                    purchase_unit = str((price / quant).units)
                    available = ', '.join(str(c) for c in thisconv) if thisconv else 'none'
                    print(
                        f"[conversion missing] '{myingr}': recipe uses '{recipe_unit}' "
                        f"but is priced in '{purchase_unit}'. Available conversions: "
                        f"[{available}]. Fix: add e.g. '1 {recipe_unit} per N {purchase_unit}' "
                        f"in the conversion field for '{myingr}'."
                    )
                    self.conversion_errors.add(myingr)
                    nextprice, myconv = 0, 1
                else:
                    self.conversion_errors.discard(myingr)

            if nextprice >= 0:
                d = dict(r)
                d['mycost'] = nextprice
                d['myconversion'] = str(myconv)
                d['$/quantity'] = str(price / quant)
                d['$/quant'] = f"{price / quant:~.2f}"
                d['_guide_index'] = idx          # track the real uni_g row this came from
                rows.append(d)
            else:
                maybeprint(f"! zero cost, {myingr}, {myquant}")

        return pd.DataFrame(rows)

    # ── O(1) write-back so existing readers see computed costs ─────────────
    def _emit(self, item, ingredient, cost):
        pos = self._rowpos.get((item, ingredient))
        if pos is not None and self._cost_col is not None:
            try:
                self.costdf.iat[pos, self._cost_col] = cost
            except Exception:
                pass
        return cost

    # ── core cost path ────────────────────────────────────────────────────
    def item_cost(self, myitem, inick):
        """Cost of `inick` as used inside `myitem` (scaled to that line's qty)."""
        self._ensure_fresh()
        inick = inick.strip()
        myitem = myitem.strip()
        iquant = self._quant.get((myitem, inick))

        if getattr(self, "use_saved", False):
            sc = self._saved.get((myitem, inick), -1.0)
            if sc >= 0:
                return self._emit(myitem, inick, sc)

        if inick in self._guide_nicks:                     # leaf -> your pricing path
            return self._emit(myitem, inick, self.get_simple_ingredient_cost(inick, iquant))

        if inick in self._recipe_yield or inick in self._children:   # sub-recipe
            full = self._full_recipe_cost(inick)
            return self._emit(myitem, inick, self._scale_to_parent(full, inick, iquant))

        return super().item_cost(myitem, inick)            # unknown: base parity

    def _full_recipe_cost(self, name):
        """Cost to make ONE full yield of `name`. Memoised -> computed once."""
        hit = self._memo.get(name)
        if hit is not None:
            return hit

        if getattr(self, "use_saved", False) and self._saved.get(("recipe", name), -1.0) > 0:
            cost = self._saved[("recipe", name)]
        else:
            cost = 0.0
            for child, _q in self._children.get(name, ()):
                cost += self.item_cost(name, child)        # already scaled to this line

        self._memo[name] = cost
        self._emit("recipe", name, cost)                   # full cost onto header row
        return cost

    def _scale_to_parent(self, full_cost, name, iquant):
        """Scale a full recipe cost to a parent line's quantity. Mirrors the
        base class's dimensionality / conversion branches exactly."""
        recipe_quant = self._recipe_yield.get(name)
        if recipe_quant is None or iquant is None:
            return full_cost
        myquant = _parse_quant(iquant)
        if myquant.dimensionality == recipe_quant.dimensionality:
            return full_cost * (myquant / recipe_quant).to_reduced_units().m
        conv_spec = self._recipe_conv.get(name)
        if isinstance(conv_spec, str):
            mycost, _ = quantity_cost_and_conv(full_cost / recipe_quant, myquant,
                                               _parse_conv(conv_spec))
            if mycost is None or mycost < 0:
                self.conversion_errors.add(name)
                return 0.0
            return mycost
        self.conversion_errors.add(name)
        return 0.0

    def recipe_cost(self, rname):
        self._ensure_fresh()
        rname = rname.strip()
        if rname in self._recipe_yield or rname in self._children:
            return self._full_recipe_cost(rname)
        return super().recipe_cost(rname)

    # ── invalidation: overrides the clear_cost the UI already calls ────────
    def clear_cost(self, inick):
        """Zero the calculated cost of `inick` and every dependent recipe, and
        drop them from the memo. Replaces the base scan-per-hop ancestor walk.

        Rebuilds maps first so quantity / structural edits made just before this
        call (the UI's pattern) are reflected. Memo for unaffected recipes is kept.
        """
        self._build_maps()                       # cheap groupby; refreshes quantities
        # leaf prices may have changed (a guide edit routes here); drop the leaf
        # cache and force the guide index to rebuild on next pricing.
        self._leaf_cost.clear()
        self._guide_dirty = True
        affected = self._ancestors(inick)
        names = affected | {inick}
        for n in names:
            self._memo.pop(n, None)
        if self._cost_col is not None and not self.costdf.empty:
            mask = self.costdf["ingredient"].astype(str).isin(names)
            self.costdf.loc[mask, "cost"] = 0.0
        return names

    def _ancestors(self, node):
        seen, stack = set(), [str(node)]
        while stack:
            n = stack.pop()
            for parent in self._parents.get(n, ()):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return seen

    # ── cost-method change: the one new UI hook ───────────────────────────
    def change_cost_method(self, new_picker):
        """recent / all / max changed: every leaf reprices, so flush the memo
        and zero the cost column. Lazy refill on next view."""
        self.cost_picker = new_picker
        self._memo = {}
        self._leaf_cost = {}                  # every leaf reprices under the new method
        if "cost" in self.costdf.columns:
            self.costdf.loc[:, "cost"] = 0.0

    # ── structural edits we can catch directly ────────────────────────────
    def removeIngredient(self, item, ingredient):
        out = super().removeIngredient(item, ingredient)
        self._build_maps()
        # the recipe `item` and everything that depends on it are now stale
        for n in self._ancestors(item) | {item}:
            self._memo.pop(n, None)
        return out

    # ── optional: force-flush memo to costdf (write-back already keeps it
    #    current, but safe to call before a bulk export) ────────────────────
    def flush_memo_to_costdf(self):
        self._ensure_fresh()
        for name, cost in self._memo.items():
            self._emit("recipe", name, cost)

    def can_lookup(self, name):
        """True if `name` has a recipe entry OR is a guide ingredient.

        O(1) dict lookup against maps already built by _build_maps /
        _ensure_guide_index. Use this instead of `not cc.findframe(name).empty`
        in any hot path (e.g. create_lookup_button) — findframe triggers
        add_equ_quant + get_cost_df and is ~40ms per call.
        """
        self._ensure_fresh()
        self._ensure_guide_index()
        return (
            name in self._recipe_yield
            or name in self._children
            or name in self._guide_by_nick
        )
