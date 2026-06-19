from __future__ import annotations

from typing import Any


class LanguagePackNode:
    def __init__(
        self,
        node: Any,
        parent: LanguagePackNode | None = None,
        index: int | None = None,
    ) -> None:
        self._node = node
        self._parent = parent
        self._index = index

    @property
    def type(self) -> str:
        return self._node.kind()

    @property
    def children(self) -> list[LanguagePackNode]:
        return [
            LanguagePackNode(self._node.child(i), self, i)
            for i in range(self._node.child_count())
        ]

    @property
    def start_byte(self) -> int:
        return self._node.start_byte()

    @property
    def end_byte(self) -> int:
        return self._node.end_byte()

    @property
    def start_point(self) -> tuple[int, int]:
        point = self._node.start_position()
        return (point.row, point.column)

    @property
    def end_point(self) -> tuple[int, int]:
        point = self._node.end_position()
        return (point.row, point.column)

    @property
    def prev_sibling(self) -> LanguagePackNode | None:
        if self._parent is None or self._index is None or self._index == 0:
            return None
        index = self._index - 1
        return LanguagePackNode(self._parent._node.child(index), self._parent, index)

    def child_by_field_name(self, name: str) -> LanguagePackNode | None:
        child = self._node.child_by_field_name(name)
        if child is None:
            return None
        for index in range(self._node.child_count()):
            if self._node.child(index) == child:
                return LanguagePackNode(child, self, index)
        return LanguagePackNode(child)


def root_node_for_tree(tree: Any) -> Any:
    root_node = tree.root_node() if callable(tree.root_node) else tree.root_node
    if hasattr(root_node, "children"):
        return root_node
    return LanguagePackNode(root_node)
