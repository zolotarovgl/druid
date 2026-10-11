"""Origin of an orthogroup on a species tree: the most recent common ancestor (MRCA) of its
member species, i.e. the node of the single gain under Dollo parsimony (one gain, losses
only).  Standard library only, so the step4 workflow can import it unchanged.
Spec: docs/superpowers/specs/2026-10-11-phylocli-og-origin-design.md"""
from __future__ import annotations

from collections import namedtuple
from typing import Iterable, Optional

Origin = namedtuple("Origin", "label depth")     # depth = edges from the root (root = 0)


class Node:
    __slots__ = ("name", "children", "parent", "depth")

    def __init__(self, name: str = "", parent: "Optional[Node]" = None):
        self.name, self.children, self.parent = name, [], parent
        self.depth = 0 if parent is None else parent.depth + 1


def parse_newick(text: str) -> Node:
    """One newick tree: polytomies, branch lengths (dropped), internal labels (kept, dots
    included).  Iterative, so deep trees do not hit the recursion limit.  ValueError on an
    unbalanced or empty tree."""
    s = "".join(text.split())
    n, i = len(s), 0
    root: Optional[Node] = None
    cur: Optional[Node] = None

    def label(i: int):
        j = i
        while j < n and s[j] not in ",();":
            j += 1
        return s[i:j].split(":", 1)[0], j

    while i < n:
        c = s[i]
        if c == ";":
            break
        if c == "(":
            if root is not None and cur is None:
                raise ValueError("newick: text after the end of the tree")
            node = Node(parent=cur)
            if cur is None:
                root = node
            else:
                cur.children.append(node)
            cur, i = node, i + 1
        elif c == ",":
            if cur is None:
                raise ValueError("newick: ',' outside parentheses")
            i += 1
        elif c == ")":
            if cur is None:
                raise ValueError("newick: unbalanced ')'")
            cur.name, i = label(i + 1)
            cur = cur.parent
        else:
            name, i = label(i)
            if cur is None:
                if root is not None:
                    raise ValueError("newick: text after the end of the tree")
                root = Node(name)                 # a one-tip tree
            else:
                cur.children.append(Node(name, cur))
    if root is None:
        raise ValueError("newick: empty tree")
    if cur is not None:
        raise ValueError("newick: unbalanced '('")
    if i < n and s[i + 1:]:                        # anything after the first ';'
        raise ValueError("newick: text after the end of the tree")
    return root


class OriginTree:
    """A species tree to place orthogroups on.  `origin(species)` = Origin(label, depth) of the
    MRCA of the species that are tips; None when none is.  Label: the node's name; an
    unlabelled node = '~' + its nearest labelled ancestor; the unlabelled root = 'root'."""

    def __init__(self, text: str):
        self.root = parse_newick(text)
        self._tip: dict = {}
        stack = [self.root]
        while stack:
            nd = stack.pop()
            if nd.children:
                stack.extend(nd.children)
            elif nd.name:
                if nd.name in self._tip:
                    raise ValueError(f"newick: tip {nd.name} occurs twice")
                self._tip[nd.name] = nd

    @property
    def tips(self) -> frozenset:
        return frozenset(self._tip)

    def mrca(self, species: Iterable[str]) -> Optional[Node]:
        nodes = [self._tip[s] for s in dict.fromkeys(species) if s in self._tip]
        if not nodes:
            return None
        a = nodes[0]
        for b in nodes[1:]:
            while a.depth > b.depth:
                a = a.parent
            while b.depth > a.depth:
                b = b.parent
            while a is not b:
                a, b = a.parent, b.parent
        return a

    @staticmethod
    def label(node: Node) -> str:
        if node.name:
            return node.name
        p = node.parent
        while p is not None and not p.name:
            p = p.parent
        if p is None:
            return "root" if node.parent is None else "~root"
        return "~" + p.name

    def origin(self, species: Iterable[str]) -> Optional[Origin]:
        nd = self.mrca(species)
        return None if nd is None else Origin(self.label(nd), nd.depth)
