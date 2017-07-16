# Copyright: 2005-2011 Brian Harring <ferringb@gmail.com>
# License: GPL2/BSD

"""DepSet parsing.

Turns a DepSet (depends, rdepends, SRC_URI, license, etc) into
appropriate conditionals.
"""

__all__ = ("DepSet", "stringify_boolean")

from snakeoil.compatibility import raise_from, IGNORED_EXCEPTIONS
from snakeoil.iterables import expandable_chain
from snakeoil.sequences import iflatten_instance

from pkgcore.ebuild.atom import atom, transitive_use_atom
from pkgcore.ebuild.errors import ParseError
from pkgcore.restrictions import packages, values, boolean

try:
    from pkgcore.ebuild._depset import parse_depset
except ImportError:
    parse_depset = None


class DepSet(boolean.AndRestriction):

    """
    gentoo DepSet syntax parser
    """

    __slots__ = ("element_class", "_node_conds", "_known_conditionals")
    type = packages.package_type
    negate = False

    _evaluate_collapse = True

    # do not enable instance caching w/out adjust evaluate_depset!
    __inst_caching__ = False
    # stored for tests primarily
    parse_depset = parse_depset
    if parse_depset is not None:
        parse_depset = staticmethod(parse_depset)

    def __init__(self, restrictions='', element_class=atom,
                 node_conds=True, known_conditionals=None):
        sf = object.__setattr__
        sf(self, '_known_conditionals', known_conditionals)
        sf(self, 'element_class', element_class)
        sf(self, 'restrictions', restrictions)
        sf(self, '_node_conds', node_conds)

    @classmethod
    def parse(cls, dep_str, element_class,
              operators=None,
              element_func=None, transitive_use_atoms=False,
              allow_src_uri_file_renames=False):
        """
        :param dep_str: string abiding by DepSet syntax
        :param operators: mapping of node -> callable for special operators
            in DepSet syntax
        :param element_func: if None, element_class is used for generating
            elements, else it's used to generate elements.
            Mainly useful for when you need to curry a few args for instance
            generation, since element_class _must_ be a class
        :param element_class: class of generated elements
        """

        if not isinstance(element_class, type):
            # yes, this blocks non new style classes.  touch cookies.
            raise ValueError("element_class must be a new style class")

        if element_func is None:
            element_func = element_class

        if cls.parse_depset is not None and not (allow_src_uri_file_renames):
            restrictions = None
            if operators is None:
                has_conditionals, restrictions = cls.parse_depset(
                    dep_str, element_func,
                    boolean.AndRestriction, boolean.OrRestriction)
            else:
                for x in operators:
                    if x not in ("", "||"):
                        break
                else:
                    has_conditionals, restrictions = cls.parse_depset(
                        dep_str, element_func,
                        operators.get(""), operators.get("||"))

            if restrictions is not None:
                if not has_conditionals and transitive_use_atoms:
                    has_conditionals = cls._has_transitive_use_atoms(restrictions)
                return cls(restrictions, element_class, has_conditionals)

        restrictions = []
        if operators is None:
            operators = {"||": boolean.OrRestriction, "": boolean.AndRestriction}

        raw_conditionals = []
        depsets = [restrictions]

        node_conds = False
        words = iter(dep_str.split())
        # we specifically do it this way since expandable_chain has a bit of nasty
        # overhead to the tune of 33% slower
        if allow_src_uri_file_renames:
            words = expandable_chain(words)
        k = None
        try:
            for k in words:
                if ")" == k:
                    # no elements == error. if closures don't map up,
                    # indexerror would be chucked from trying to pop
                    # the frame so that is addressed.
                    if not depsets[-1] or not raw_conditionals:
                        raise ParseError(dep_str)
                    elif raw_conditionals[-1] in operators:
                        if len(depsets[-1]) == 1:
                            depsets[-2].append(depsets[-1][0])
                        else:
                            depsets[-2].append(
                                operators[raw_conditionals[-1]](*depsets[-1]))
                    else:
                        node_conds = True
                        c = raw_conditionals[-1]
                        if c[0] == "!":
                            c = values.ContainmentMatch(c[1:-1], negate=True)
                        else:
                            c = values.ContainmentMatch(c[:-1])

                        depsets[-2].append(
                            packages.Conditional("use", c, tuple(depsets[-1])))

                    raw_conditionals.pop()
                    depsets.pop()

                elif "(" == k:
                    k = ''
                    # push another frame on
                    depsets.append([])
                    raw_conditionals.append(k)

                elif k[-1] == '?' or k in operators:
                    # use conditional or custom op.
                    # no tokens left == bad dep_str.
                    k2 = words.next()

                    if k2 != "(":
                        raise ParseError(dep_str, k2)

                    # push another frame on
                    depsets.append([])
                    raw_conditionals.append(k)

                elif "|" in k:
                    raise ParseError(dep_str, k)
                elif allow_src_uri_file_renames:
                    try:
                        k2 = words.next()
                    except StopIteration:
                        depsets[-1].append(element_func(k))
                    else:
                        if k2 != '->':
                            depsets[-1].append(element_func(k))
                            words.appendleft((k2,))
                        else:
                            k3 = words.next()
                            # file ename.
                            depsets[-1].append(element_func(k, k3))
                else:
                    # node/element.
                    depsets[-1].append(element_func(k))

        except IGNORED_EXCEPTIONS:
            raise
        except IndexError:
            # [][-1] for a frame access, which means it was a parse error.
            raise
        except StopIteration:
            if k is None:
                raise
            raise ParseError(dep_str, k)
        except Exception as e:
            raise_from(ParseError(dep_str, e))

        # check if any closures required
        if len(depsets) != 1:
            raise ParseError(dep_str)

        if transitive_use_atoms and not node_conds:
            # localize to this scope for speed.
            element_class = transitive_use_atom
            # we can't rely on iter(self) here since it doesn't
            # descend through boolean restricts.
            node_conds = cls._has_transitive_use_atoms(restrictions)

        return cls(tuple(restrictions), element_class, node_conds)

    @staticmethod
    def _has_transitive_use_atoms(iterable):
        kls = transitive_use_atom
        ifunc = isinstance
        return any(ifunc(x, kls) for x in iflatten_instance(iterable, atom))

    def evaluate_depset(self, cond_dict, tristate_filter=None, pkg=None):
        """
        :param cond_dict: container to be used for conditional collapsing,
            typically is a use list
        :param tristate_filter: a control; if specified, must be a container
            of conditionals to lock to cond_dict.
            during processing, if it's not in tristate_filter will
            automatically enable the payload
            (regardless of the conditionals negation)
        """
        if not self.has_conditionals:
            return self

        results = []
        self.evaluate_conditionals(
            self.__class__, results,
            cond_dict, tristate_filter, force_collapse=True)

        return self.__class__(tuple(results), self.element_class, False)

    @staticmethod
    def find_cond_nodes(restriction_set, yield_non_conditionals=False):
        conditions_stack = []
        new_set = expandable_chain(restriction_set)
        for cur_node in new_set:
            if isinstance(cur_node, packages.Conditional):
                conditions_stack.append(cur_node.restriction)
                new_set.appendleft(list(cur_node.payload) + [None])
            elif isinstance(cur_node, transitive_use_atom):
                new_set.appendleft(cur_node.convert_to_conditionals())
            elif (isinstance(cur_node, boolean.base) and
                    not isinstance(cur_node, atom)):
                new_set.appendleft(cur_node.restrictions)
            elif cur_node is None:
                conditions_stack.pop()
            elif conditions_stack or yield_non_conditionals: # leaf
                yield (cur_node, conditions_stack[:])

    @property
    def node_conds(self):
        if self._node_conds is False:
            object.__setattr__(self, "_node_conds", {})
        elif self._node_conds is True:
            nc = {}

            always_required = set()

            for payload, restrictions in self.find_cond_nodes(self.restrictions, True):
                if not restrictions:
                    always_required.add(payload)
                else:
                    if len(restrictions) == 1:
                        current = restrictions[0]
                    else:
                        current = values.AndRestriction(*restrictions)

                    nc.setdefault(payload, []).append(current)

            for k in always_required:
                if k in nc:
                    del nc[k]
            for k in nc:
                nc[k] = tuple(nc[k])

            object.__setattr__(self, "_node_conds", nc)

        return self._node_conds

    @property
    def has_conditionals(self):
        return bool(self._node_conds)

    @property
    def known_conditionals(self):
        if self._node_conds is False:
            return frozenset()
        if self._known_conditionals is None:
            kc = set()
            for payload, restrictions in self.find_cond_nodes(self.restrictions):
                kc.update(iflatten_instance(x.vals for x in restrictions))
            kc = frozenset(kc)
            object.__setattr__(self, "_known_conditionals", kc)
            return kc
        return self._known_conditionals

    def match(self, *a):
        raise NotImplementedError

    def slotdep_str(self, domain):
        return stringify_boolean(self, domain=domain)

    force_False = force_True = match

    def __str__(self):
        return stringify_boolean(self)

    def __iter__(self):
        return iter(self.restrictions)

    def __getitem__(self, key):
        return self.restrictions[key]


def stringify_boolean(node, func=str, domain=None):
    """func is used to stringify the actual content. Useful for fetchables."""
    l = []
    if isinstance(node, DepSet):
        for x in node.restrictions:
            _internal_stringify_boolean(x, domain, func, l.append)
    else:
        _internal_stringify_boolean(node, domain, func, l.append)
    return ' '.join(l)

def _internal_stringify_boolean(node, domain, func, visit):
    """func is used to stringify the actual content. Useful for fetchables."""

    if isinstance(node, boolean.OrRestriction):
        visit("|| (")
        iterable = node.restrictions
    elif (isinstance(node, boolean.AndRestriction) and
            not isinstance(node, atom)):
        visit("(")
        iterable = node.restrictions
    elif isinstance(node, packages.Conditional):
        assert len(node.restriction.vals) == 1
        iterable = node.payload
        visit("%s%s? (" % (
            node.restriction.negate and "!" or "",
            list(node.restriction.vals)[0]))
    else:
        if (domain is not None and
                (isinstance(node, atom) and node.slot_operator == '=')):
            pkg = max(sorted(domain.all_livefs_repos.itermatch(node)))
            object.__setattr__(node, "slot", pkg.slot)
            object.__setattr__(node, "subslot", pkg.subslot)
        visit(func(node))
        return
    for node in iterable:
        _internal_stringify_boolean(node, domain, func, visit)
    visit(")")
