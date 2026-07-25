"""Slave register editor (PySide6)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modbus_sim.config import RegisterKind, ValueKind
from modbus_sim.datastore import (
    SlaveRegistry,
    format_decoded_display,
    parse_decoded_input,
    registry,
    validate_address,
)
from modbus_sim.models import RegisterPoint

GRID_COLUMNS = ("Addr", "Raw", "Decoded", "Datatype", "Tag")
GRID_FIELDS = ("addr", "raw", "decoded", "datatype", "tag")
DATATYPE_COL = GRID_FIELDS.index("datatype")
# レジスタ表で選べる型（自由入力で不正値にならないようリスト固定）
DATATYPE_CHOICES = (ValueKind.UINT16, ValueKind.INT16, ValueKind.INT32)

_ACTIVITY_COLORS = {
    "active": "green",
    "idle": "gray",
    "off": "#cccccc",
}


class SlavePanel(QWidget):
    def __init__(
        self,
        slave_registry: SlaveRegistry | None = None,
        on_change: Callable[[], None] | None = None,
        *,
        title: str = "スレーブ設定値",
    ) -> None:
        super().__init__()
        self._registry = slave_registry or registry
        self._on_change = on_change
        self._grid_enabled = True
        self._server_running = False
        self._draft: RegisterPoint | None = None
        self._row_meta: list[RegisterPoint | None] = []
        self._updating_table = False
        self._activity_dots: dict[int, QLabel] = {}

        self.slave_list = QListWidget()
        self.slave_list.currentRowChanged.connect(self._on_slave_selected)

        self.slave_tag_field = QLineEdit()
        self.slave_tag_field.setPlaceholderText("機器名")
        self.slave_tag_field.textChanged.connect(self._save_slave_tag)

        self.new_slave_id_field = QLineEdit()
        self.new_slave_id_field.setPlaceholderText("ID")
        self.new_slave_id_field.setFixedWidth(60)
        self.new_slave_id_field.returnPressed.connect(self._add_slave)

        self.add_slave_button = QPushButton("+")
        self.add_slave_button.setFixedWidth(32)
        self.add_slave_button.setToolTip("Slave 追加")
        self.add_slave_button.clicked.connect(self._add_slave)

        self.table = QTableWidget(0, len(GRID_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(GRID_COLUMNS))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellChanged.connect(self._on_cell_changed)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #b00020;")

        slave_group = QGroupBox("Slave ID")
        slave_layout = QVBoxLayout(slave_group)
        add_row = QHBoxLayout()
        add_row.addStretch()
        add_row.addWidget(self.new_slave_id_field)
        add_row.addWidget(self.add_slave_button)
        slave_layout.addLayout(add_row)
        slave_layout.addWidget(self.slave_list, stretch=1)
        slave_layout.addWidget(self.slave_tag_field)

        left = QVBoxLayout()
        left.addWidget(slave_group, stretch=1)

        right = QVBoxLayout()
        right.addWidget(
            QLabel("Raw = 10進 / Decoded = 16進（0x あり・なし可）。セル編集後に確定されます。")
        )
        right.addWidget(self.table, stretch=1)

        body = QHBoxLayout()
        body.addLayout(left, stretch=0)
        body.addLayout(right, stretch=1)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title, styleSheet="font-weight: bold; font-size: 13px;"))
        layout.addLayout(body)
        layout.addWidget(self._status)

        self._rebuild()

    def set_grid_enabled(self, enabled: bool) -> None:
        self._grid_enabled = enabled
        self._rebuild_table()

    def set_server_running(self, running: bool) -> None:
        self._server_running = running

    def refresh_activity(self, any_server_running: bool) -> None:
        for slave_id, dot in self._activity_dots.items():
            state = self._registry.activity_state(slave_id, any_server_running=any_server_running)
            dot.setStyleSheet(f"color: {_ACTIVITY_COLORS[state]}; font-size: 12px;")

    def refresh_from_server(self) -> bool:
        if self.table.state() == QAbstractItemView.State.EditingState:
            return False
        changed = self._registry.sync_from_server()
        if changed:
            self._rebuild_table()
        return changed

    def _rebuild(self) -> None:
        self._rebuild_slave_list()
        self._sync_slave_tag_field()
        self._rebuild_table()

    def _sync_slave_tag_field(self) -> None:
        self.slave_tag_field.blockSignals(True)
        self.slave_tag_field.setText(self._registry.get_tag(self._registry.selected_slave_id))
        self.slave_tag_field.blockSignals(False)

    def _rebuild_slave_list(self) -> None:
        selected = self._registry.selected_slave_id
        self.slave_list.blockSignals(True)
        self.slave_list.clear()
        self._activity_dots.clear()
        for slave_id in self._registry.list_slave_ids():
            tag = self._registry.get_tag(slave_id)
            tag_label = tag if tag else "(未設定)"
            state = self._registry.activity_state(
                slave_id, any_server_running=self._server_running
            )
            row_widget, dot = self._make_slave_row(slave_id, tag_label, state)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, slave_id)
            item.setSizeHint(row_widget.sizeHint())
            self.slave_list.addItem(item)
            self.slave_list.setItemWidget(item, row_widget)
            self._activity_dots[slave_id] = dot
            if slave_id == selected:
                self.slave_list.setCurrentItem(item)
        self.slave_list.blockSignals(False)

    def _make_slave_row(self, slave_id: int, tag_label: str, state: str) -> tuple[QWidget, QLabel]:
        dot = QLabel("●")
        dot.setFixedWidth(16)
        dot.setStyleSheet(f"color: {_ACTIVITY_COLORS[state]}; font-size: 12px;")
        text = QLabel(f"{slave_id}\n{tag_label}")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(dot)
        layout.addWidget(text, stretch=1)
        return row, dot

    def _make_datatype_combo(self, row_index: int, current: ValueKind) -> QComboBox:
        combo = QComboBox()
        for kind in DATATYPE_CHOICES:
            combo.addItem(kind.value, kind)
        index = combo.findData(current if current in DATATYPE_CHOICES else ValueKind.UINT16)
        combo.setCurrentIndex(max(index, 0))
        combo.setEnabled(self._grid_enabled)
        combo.currentIndexChanged.connect(
            lambda _idx, r=row_index: self._on_datatype_changed(r)
        )
        return combo

    def _rebuild_table(self) -> None:
        slave = self._registry.get_slave(self._registry.selected_slave_id)
        points = slave.list_points()
        self._row_meta = [*points, None]
        self._updating_table = True
        self.table.setRowCount(len(self._row_meta))
        for row_index, point in enumerate(self._row_meta):
            source = point or self._draft or RegisterPoint(
                address=-1,
                kind=RegisterKind.HOLDING_REGISTER,
                datatype=ValueKind.UINT16,
            )
            addr_value = "" if source.address < 0 else str(source.address)
            raw_value = "" if source.address < 0 and point is None and not self._draft else str(source.raw)
            decoded_value = "" if source.address < 0 else format_decoded_display(source)
            values = [addr_value, raw_value, decoded_value, None, source.tag]
            for col, text in enumerate(values):
                if col == DATATYPE_COL:
                    self.table.setCellWidget(
                        row_index, col, self._make_datatype_combo(row_index, source.datatype)
                    )
                    continue
                item = QTableWidgetItem(text or "")
                if not self._grid_enabled:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, col, item)
        self._updating_table = False

    def _on_slave_selected(self, _row: int) -> None:
        item = self.slave_list.currentItem()
        if item is None:
            return
        slave_id = item.data(Qt.ItemDataRole.UserRole)
        if slave_id is None:
            return
        self._registry.selected_slave_id = int(slave_id)
        self._draft = None
        self._rebuild()
        if self._on_change:
            self._on_change()

    def _on_datatype_changed(self, row: int) -> None:
        if self._updating_table or not self._grid_enabled:
            return
        combo = self.table.cellWidget(row, DATATYPE_COL)
        if not isinstance(combo, QComboBox):
            return
        kind = combo.currentData()
        if not isinstance(kind, ValueKind):
            return
        point = self._row_meta[row] if row < len(self._row_meta) else None
        self._commit_cell(
            self._registry.selected_slave_id,
            point,
            "datatype",
            kind.value,
            row_index=row,
        )

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating_table or not self._grid_enabled:
            return
        if col == DATATYPE_COL:
            return
        item = self.table.item(row, col)
        if item is None:
            return
        point = self._row_meta[row] if row < len(self._row_meta) else None
        self._commit_cell(
            self._registry.selected_slave_id,
            point,
            GRID_FIELDS[col],
            item.text(),
            row_index=row,
        )

    def _commit_cell(
        self,
        slave_id: int,
        point: RegisterPoint | None,
        field: str,
        value: str,
        *,
        row_index: int | None = None,
    ) -> bool:
        try:
            current = point or self._draft or RegisterPoint(
                address=-1,
                kind=RegisterKind.HOLDING_REGISTER,
                datatype=ValueKind.UINT16,
            )
            updated = RegisterPoint(
                address=current.address,
                kind=current.kind,
                datatype=current.datatype,
                tag=current.tag,
                raw=current.raw,
            )
            if field == "addr":
                if not value.strip():
                    return False
                updated.address = int(value)
            elif field == "raw":
                if not value.strip() and updated.address < 0:
                    return False
                updated.raw = int(value or "0")
            elif field == "decoded":
                if not value.strip() and updated.address < 0:
                    return False
                updated.raw = parse_decoded_input(value, updated.datatype)
            elif field == "datatype":
                if not value.strip():
                    return False
                updated.datatype = ValueKind(value.strip())
                if updated.datatype not in DATATYPE_CHOICES:
                    raise ValueError(
                        f"Datatype は {', '.join(k.value for k in DATATYPE_CHOICES)} から選択してください"
                    )
            elif field == "tag":
                updated.tag = value.strip()
            else:
                return False

            if updated == current and point is not None:
                return False

            if updated.address < 0:
                self._draft = updated
                self._rebuild_table()
                return True

            validate_address(updated.address, updated.datatype)

            slave = self._registry.get_slave(slave_id)
            structural = point is None or (point is not None and updated.key != point.key)
            if point and updated.key != point.key:
                slave.points.pop(point.key, None)
            slave.upsert_point(updated)
            self._draft = None
            self._status.setText("")

            if structural or field == "datatype":
                self._rebuild_table()
            elif row_index is not None:
                self._row_meta[row_index] = updated
                self._refresh_row_values(row_index, updated, edited_field=field)
            if self._on_change:
                self._on_change()
            return structural
        except (ValueError, KeyError) as exc:
            self._status.setText(str(exc))
            return False

    def _refresh_row_values(self, row_index: int, point: RegisterPoint, *, edited_field: str) -> None:
        self._updating_table = True
        updates: dict[int, str] = {}
        if edited_field != "addr":
            updates[0] = str(point.address)
        if edited_field != "raw":
            updates[1] = str(point.raw)
        if edited_field != "decoded":
            updates[2] = format_decoded_display(point)
        if edited_field != "tag":
            updates[4] = point.tag
        for col_index, text in updates.items():
            item = self.table.item(row_index, col_index)
            if item is not None:
                item.setText(text)
        if edited_field != "datatype":
            combo = self.table.cellWidget(row_index, DATATYPE_COL)
            if isinstance(combo, QComboBox):
                index = combo.findData(point.datatype)
                if index >= 0:
                    combo.setCurrentIndex(index)
        self._updating_table = False

    def _save_slave_tag(self, text: str) -> None:
        try:
            slave_id = self._registry.selected_slave_id
            new_tag = text.strip()
            if new_tag == self._registry.get_tag(slave_id):
                return
            self._registry.set_tag(slave_id, new_tag)
            self._rebuild_slave_list()
            if self._on_change:
                self._on_change()
        except KeyError as exc:
            self._status.setText(str(exc))

    def _add_slave(self) -> None:
        try:
            slave_id = int(self.new_slave_id_field.text() or "0")
            self._registry.add_slave(slave_id)
            self._registry.selected_slave_id = slave_id
            self.new_slave_id_field.clear()
            self._status.setText("")
            self._rebuild()
            if self._on_change:
                self._on_change()
        except ValueError as exc:
            QMessageBox.warning(self, "エラー", str(exc))
