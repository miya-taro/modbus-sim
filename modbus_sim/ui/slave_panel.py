"""Slave register editor (PySide6)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modbus_sim.config import REGISTER_COUNT, RegisterKind, ValueKind
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
ADDR_COL = GRID_FIELDS.index("addr")
RAW_COL = GRID_FIELDS.index("raw")
DECODED_COL = GRID_FIELDS.index("decoded")
DATATYPE_COL = GRID_FIELDS.index("datatype")
TAG_COL = GRID_FIELDS.index("tag")

# レジスタ表で選べる種別・型（自由入力で不正値にならないようリスト固定）
KIND_CHOICES = (
    RegisterKind.HOLDING_REGISTER,
    RegisterKind.INPUT_REGISTER,
    RegisterKind.COIL,
    RegisterKind.DISCRETE_INPUT,
)
_KIND_LABELS = {
    RegisterKind.HOLDING_REGISTER: "Holding Register",
    RegisterKind.INPUT_REGISTER: "Input Register",
    RegisterKind.COIL: "Coil",
    RegisterKind.DISCRETE_INPUT: "Discrete Input",
}
DATATYPE_CHOICES = (ValueKind.UINT16, ValueKind.INT16, ValueKind.INT32)
# Coil / Discrete Input は 1bit 固定のため Datatype は bool のみ選択可
BIT_DATATYPE_CHOICES = (ValueKind.BOOL,)


def _datatype_choices_for(kind: RegisterKind) -> tuple[ValueKind, ...]:
    if kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
        return BIT_DATATYPE_CHOICES
    return DATATYPE_CHOICES


def _default_datatype_for(kind: RegisterKind) -> ValueKind:
    return _datatype_choices_for(kind)[0]


class _DatatypeDelegate(QStyledItemDelegate):
    """Datatype 列専用。常時コンボを置かず、編集時だけコンボを出す（軽量・矢印キー可）。"""

    def __init__(self, panel: "SlavePanel") -> None:
        super().__init__(panel)
        self._panel = panel

    def createEditor(self, parent, option, index):  # noqa: N802
        if not self._panel._grid_enabled:
            return None
        row = index.row()
        point = self._panel._row_meta[row] if row < len(self._panel._row_meta) else None
        kind = point.kind if point is not None else self._panel.active_kind
        choices = _datatype_choices_for(kind)
        if len(choices) <= 1:
            return None
        combo = QComboBox(parent)
        for datatype in choices:
            combo.addItem(datatype.value, datatype)
        # 選択確定ですぐ閉じる（ドロップダウン中の都度コミットはしない）
        combo.activated.connect(lambda _i, editor=combo: self._commit_and_close(editor))
        # 編集開始と同時に候補を開き、体感遅延を減らす
        QTimer.singleShot(0, combo.showPopup)
        return combo

    def _commit_and_close(self, editor: QComboBox) -> None:
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        if not isinstance(editor, QComboBox):
            return
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        found = editor.findText(text)
        editor.setCurrentIndex(max(found, 0))

    def setModelData(self, editor, model, index) -> None:  # noqa: N802
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        editor.setGeometry(option.rect)

_ACTIVITY_COLORS = {
    "active": "green",
    "idle": "gray",
    "off": "#cccccc",
}

_KIND_BY_LABEL = {label.lower(): kind for kind, label in _KIND_LABELS.items()}

# コピー/貼り付けの TSV 列順
_PASTE_COLUMNS = ("Addr", "Kind", "Datatype", "Raw", "Tag")


def _parse_kind(text: str) -> RegisterKind:
    text = text.strip()
    try:
        return RegisterKind(text.lower())
    except ValueError:
        pass
    kind = _KIND_BY_LABEL.get(text.lower())
    if kind is None:
        raise ValueError(f"Kind '{text}' を解釈できません")
    return kind


def _parse_datatype(text: str, kind: RegisterKind) -> ValueKind:
    text = text.strip()
    try:
        datatype = ValueKind(text.lower())
    except ValueError as exc:
        raise ValueError(f"Datatype '{text}' を解釈できません") from exc
    allowed = _datatype_choices_for(kind)
    if datatype not in allowed:
        raise ValueError(
            f"この Kind では Datatype は {', '.join(k.value for k in allowed)} のみ有効です"
        )
    return datatype


class RangeAddDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        default_kind: RegisterKind = RegisterKind.HOLDING_REGISTER,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("範囲追加")
        self._kind = default_kind

        self.start_address = QSpinBox()
        self.start_address.setRange(0, REGISTER_COUNT - 1)

        self.count_field = QSpinBox()
        self.count_field.setRange(1, 2000)
        self.count_field.setValue(1)

        self.datatype_combo = QComboBox()
        for datatype in _datatype_choices_for(default_kind):
            self.datatype_combo.addItem(datatype.value, datatype)
        self.datatype_combo.setEnabled(len(_datatype_choices_for(default_kind)) > 1)

        self.raw_field = QLineEdit("0")
        self.raw_field.setToolTip("すべての行に設定する初期値（10進）")

        self.tag_prefix_field = QLineEdit()
        self.tag_prefix_field.setPlaceholderText("空欄可（例: Sensor → Sensor0, Sensor1, ...）")

        form = QFormLayout()
        form.addRow("Kind", QLabel(_KIND_LABELS[default_kind]))
        form.addRow("開始アドレス", self.start_address)
        form.addRow("件数", self.count_field)
        form.addRow("Datatype", self.datatype_combo)
        form.addRow("初期値 (10進)", self.raw_field)
        form.addRow("タグ接頭辞", self.tag_prefix_field)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("int32 はアドレスを2つ消費するため、開始アドレスから2ずつ進みます。"))
        layout.addWidget(buttons)

    def values(self) -> tuple[int, int, RegisterKind, ValueKind, int, str]:
        datatype = ValueKind(self.datatype_combo.currentData())
        try:
            raw = int(self.raw_field.text().strip() or "0")
        except ValueError as exc:
            raise ValueError("初期値は整数で入力してください") from exc
        return (
            self.start_address.value(),
            self.count_field.value(),
            self._kind,
            datatype,
            raw,
            self.tag_prefix_field.text().strip(),
        )


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
        self._active_kind = RegisterKind.HOLDING_REGISTER
        self._draft: RegisterPoint | None = None
        self._row_meta: list[RegisterPoint | None] = []
        self._updating_table = False
        self._activity_dots: dict[int, QLabel] = {}

        self.slave_search_field = QLineEdit()
        self.slave_search_field.setPlaceholderText("検索 (ID / 機器名)")
        self.slave_search_field.textChanged.connect(self._apply_slave_filter)

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

        self.remove_slave_button = QPushButton("選択中の Slave を削除")
        self.remove_slave_button.setToolTip("選択中の Slave を削除（Delete キーでも可）")
        self.remove_slave_button.clicked.connect(self._remove_slave)

        self.kind_tabs = QTabWidget()
        self.kind_tabs.setDocumentMode(True)
        for kind in KIND_CHOICES:
            self.kind_tabs.addTab(QWidget(), _KIND_LABELS[kind])
        self.kind_tabs.currentChanged.connect(self._on_kind_tab_changed)

        self.table = QTableWidget(0, len(GRID_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(GRID_COLUMNS))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setItemDelegateForColumn(DATATYPE_COL, _DatatypeDelegate(self))
        self.table.cellChanged.connect(self._on_cell_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self._install_shortcuts()

        self._status = QLabel("")
        self._status.setStyleSheet("color: #b00020;")

        slave_group = QGroupBox("Slave ID")
        slave_layout = QVBoxLayout(slave_group)
        add_row = QHBoxLayout()
        add_row.addStretch()
        add_row.addWidget(self.new_slave_id_field)
        add_row.addWidget(self.add_slave_button)
        slave_layout.addLayout(add_row)
        slave_layout.addWidget(self.slave_search_field)
        slave_layout.addWidget(self.slave_list, stretch=1)
        slave_layout.addWidget(self.remove_slave_button)
        slave_layout.addWidget(self.slave_tag_field)

        left = QVBoxLayout()
        left.addWidget(slave_group, stretch=1)

        self.register_search_field = QLineEdit()
        self.register_search_field.setPlaceholderText("検索 (Addr / Tag)")
        self.register_search_field.textChanged.connect(self._apply_register_filter)

        self.range_add_button = QPushButton("範囲追加...")
        self.range_add_button.setToolTip("現在の Kind タブ向けに、連続アドレスをまとめて追加します")
        self.range_add_button.clicked.connect(self._open_range_add_dialog)

        self.import_map_button = QPushButton("CSV/TSV取込...")
        self.import_map_button.setToolTip(
            "レジスタマップ（Addr/Kind/Datatype/Raw/Tag）を CSV/TSV から取り込みます"
        )
        self.import_map_button.clicked.connect(self._import_register_map_file)

        register_toolbar = QHBoxLayout()
        register_toolbar.addWidget(self.register_search_field, stretch=1)
        register_toolbar.addWidget(self.range_add_button)
        register_toolbar.addWidget(self.import_map_button)

        right = QVBoxLayout()
        right.addWidget(
            QLabel(
                "Kind は上のタブで切り替えます（表に Kind 列はありません）。"
                "キーボードで Addr → Raw → Decoded → Datatype → Tag を移動できます。\n"
                "Datatype はセルで Enter / ダブルクリックすると候補が出ます（通常時はテキストなので軽く動きます）。"
                "Coil / Discrete Input の Datatype は bool 固定、"
                "Holding / Input Register は uint16 / int16 / int32 です。\n"
                "範囲追加・CSV/TSV取込・コピー/貼り付けで一括設定できます。"
            )
        )
        right.addWidget(self.kind_tabs)
        right.addLayout(register_toolbar)
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

    @property
    def active_kind(self) -> RegisterKind:
        return self._active_kind

    def set_active_kind(self, kind: RegisterKind) -> None:
        index = KIND_CHOICES.index(kind)
        if self.kind_tabs.currentIndex() != index:
            self.kind_tabs.setCurrentIndex(index)
        else:
            self._apply_active_kind(kind)

    def _on_kind_tab_changed(self, index: int) -> None:
        if 0 <= index < len(KIND_CHOICES):
            self._apply_active_kind(KIND_CHOICES[index])

    def _apply_active_kind(self, kind: RegisterKind) -> None:
        if self._active_kind == kind and self._draft is None:
            self._rebuild_table()
            return
        self._active_kind = kind
        if self._draft is not None and self._draft.kind != kind:
            self._draft = None
        self._rebuild_table()

    def _new_draft_point(self) -> RegisterPoint:
        return RegisterPoint(
            address=-1,
            kind=self._active_kind,
            datatype=_default_datatype_for(self._active_kind),
        )

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
        self.remove_slave_button.setEnabled(len(self._registry.list_slave_ids()) > 1)
        self._apply_slave_filter()

    def _apply_slave_filter(self, _text: str = "") -> None:
        query = self.slave_search_field.text().strip().lower()
        for row in range(self.slave_list.count()):
            item = self.slave_list.item(row)
            slave_id = item.data(Qt.ItemDataRole.UserRole)
            tag = self._registry.get_tag(slave_id) if slave_id is not None else ""
            haystack = f"{slave_id} {tag}".lower()
            item.setHidden(bool(query) and query not in haystack)

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

    def _close_active_editor(self) -> None:
        """表再構築前に開いているエディタを閉じ、Qt の警告/編集不能を防ぐ。"""
        if self.table.state() != QAbstractItemView.State.EditingState:
            return
        current = self.table.currentItem()
        if current is not None:
            self.table.closePersistentEditor(current)
        focus = QApplication.focusWidget()
        if focus is not None and (focus is self.table or self.table.isAncestorOf(focus)):
            self.table.setFocus(Qt.FocusReason.OtherFocusReason)

    def _rebuild_table(self) -> None:
        self._close_active_editor()
        slave = self._registry.get_slave(self._registry.selected_slave_id)
        points = [p for p in slave.list_points() if p.kind == self._active_kind]
        draft = self._draft if self._draft is not None and self._draft.kind == self._active_kind else None
        self._row_meta = [*points, None]
        self._updating_table = True
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self._row_meta))
            for row_index, point in enumerate(self._row_meta):
                source = point or draft or self._new_draft_point()
                addr_value = "" if source.address < 0 else str(source.address)
                raw_value = (
                    "" if source.address < 0 and point is None and draft is None else str(source.raw)
                )
                decoded_value = "" if source.address < 0 else format_decoded_display(source)
                datatype_editable = (
                    self._grid_enabled and len(_datatype_choices_for(source.kind)) > 1
                )
                values = [
                    addr_value,
                    raw_value,
                    decoded_value,
                    source.datatype.value,
                    source.tag,
                ]
                for col, text_value in enumerate(values):
                    item = QTableWidgetItem(text_value or "")
                    if not self._grid_enabled or (col == DATATYPE_COL and not datatype_editable):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row_index, col, item)
        finally:
            self.table.setUpdatesEnabled(True)
            self._updating_table = False
        self._apply_register_filter()

    def _apply_register_filter(self, _text: str = "") -> None:
        query = self.register_search_field.text().strip().lower()
        for row in range(self.table.rowCount()):
            if row >= len(self._row_meta) or self._row_meta[row] is None:
                self.table.setRowHidden(row, False)
                continue
            addr_item = self.table.item(row, ADDR_COL)
            tag_item = self.table.item(row, TAG_COL)
            haystack = f"{addr_item.text() if addr_item else ''} {tag_item.text() if tag_item else ''}".lower()
            self.table.setRowHidden(row, bool(query) and query not in haystack)

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

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating_table or not self._grid_enabled:
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
        col = GRID_FIELDS.index(field) if field in GRID_FIELDS else None
        try:
            current = point or self._draft or self._new_draft_point()
            updated = RegisterPoint(
                address=current.address,
                kind=current.kind if point is not None else self._active_kind,
                datatype=current.datatype,
                tag=current.tag,
                raw=current.raw,
            )
            if point is None and updated.kind != self._active_kind:
                updated.kind = self._active_kind
                updated.datatype = _default_datatype_for(self._active_kind)
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
                new_datatype = ValueKind(value.strip())
                allowed = _datatype_choices_for(updated.kind)
                if new_datatype not in allowed:
                    raise ValueError(
                        f"この Kind では Datatype は {', '.join(k.value for k in allowed)} のみ選択できます"
                    )
                updated.datatype = new_datatype
            elif field == "tag":
                updated.tag = value.strip()
            else:
                return False

            if updated == current and point is not None:
                return False

            if updated.address < 0:
                self._draft = updated
                if row_index is not None and col is not None:
                    self._mark_cell_error(row_index, col, None)
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

            if structural:
                self._rebuild_table()
            elif row_index is not None:
                self._row_meta[row_index] = updated
                self._refresh_row_values(row_index, updated, edited_field=field)
                if col is not None:
                    self._mark_cell_error(row_index, col, None)
            if self._on_change:
                self._on_change()
            return structural
        except (ValueError, KeyError) as exc:
            self._status.setText(str(exc))
            if row_index is not None and col is not None:
                self._mark_cell_error(row_index, col, str(exc))
            return False

    def _mark_cell_error(self, row_index: int, col: int, message: str | None) -> None:
        item = self.table.item(row_index, col)
        if item is None:
            return
        if message:
            item.setBackground(QColor("#fdecea"))
            item.setToolTip(message)
        else:
            item.setBackground(QBrush())
            item.setToolTip("")

    def _refresh_row_values(self, row_index: int, point: RegisterPoint, *, edited_field: str) -> None:
        self._updating_table = True
        updates: dict[int, str] = {}
        if edited_field != "addr":
            updates[ADDR_COL] = str(point.address)
        if edited_field != "raw":
            updates[RAW_COL] = str(point.raw)
        if edited_field != "decoded":
            updates[DECODED_COL] = format_decoded_display(point)
        if edited_field != "datatype":
            updates[DATATYPE_COL] = point.datatype.value
        if edited_field != "tag":
            updates[TAG_COL] = point.tag
        for col_index, text in updates.items():
            item = self.table.item(row_index, col_index)
            if item is not None:
                item.setText(text)
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

    def _remove_slave(self) -> None:
        slave_id = self._registry.selected_slave_id
        tag = self._registry.get_tag(slave_id)
        label = f"Slave {slave_id}" + (f"（{tag}）" if tag else "")
        confirm = QMessageBox.question(
            self,
            "確認",
            f"{label} を削除しますか？\nレジスタ設定も含めて削除され、元に戻せません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._registry.remove_slave(slave_id)
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "エラー", str(exc))
            return
        self._draft = None
        self._status.setText("")
        self._rebuild()
        if self._on_change:
            self._on_change()

    def _selected_data_rows(self) -> list[int]:
        rows = {index.row() for index in self.table.selectedIndexes()}
        return sorted(
            row for row in rows if row < len(self._row_meta) and self._row_meta[row] is not None
        )

    def _delete_rows(self, rows: list[int]) -> None:
        if not rows or not self._grid_enabled:
            return
        points = [self._row_meta[row] for row in rows if self._row_meta[row] is not None]
        if not points:
            return
        if len(points) == 1:
            point = points[0]
            message = f"Addr {point.address}（{_KIND_LABELS[point.kind]}）を削除しますか？"
        else:
            message = f"選択した {len(points)} 件のレジスタを削除しますか？"
        confirm = QMessageBox.question(
            self,
            "確認",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        slave = self._registry.get_slave(self._registry.selected_slave_id)
        for point in points:
            slave.remove_point(point.address, point.kind)
        self._draft = None
        self._status.setText("")
        self._rebuild_table()
        if self._on_change:
            self._on_change()

    def _show_table_context_menu(self, pos) -> None:
        if not self._grid_enabled:
            return
        rows = self._selected_data_rows()
        row_at_pos = self.table.rowAt(pos.y())
        if row_at_pos >= 0 and row_at_pos < len(self._row_meta) and self._row_meta[row_at_pos] is not None:
            if row_at_pos not in rows:
                rows = [row_at_pos]
        menu = QMenu(self)
        if rows:
            copy_label = "コピー" if len(rows) == 1 else f"選択した {len(rows)} 行をコピー"
            copy_action = menu.addAction(copy_label)
            copy_action.triggered.connect(lambda: self._copy_rows(rows))

            dup_label = "複製" if len(rows) == 1 else f"選択した {len(rows)} 行を複製"
            dup_action = menu.addAction(dup_label)
            dup_action.triggered.connect(lambda: self._duplicate_rows(rows))

        paste_action = menu.addAction("貼り付け")
        paste_action.setEnabled(bool(QApplication.clipboard().text().strip()))
        paste_action.triggered.connect(self._paste_rows)

        if rows:
            menu.addSeparator()
            label = "この行を削除" if len(rows) == 1 else f"選択した {len(rows)} 行を削除"
            delete_action = menu.addAction(label)
            delete_action.triggered.connect(lambda: self._delete_rows(rows))

        if not rows and not paste_action.isEnabled():
            return
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_rows(self, rows: list[int]) -> None:
        points = [self._row_meta[row] for row in rows if self._row_meta[row] is not None]
        if not points:
            return
        lines = ["\t".join(_PASTE_COLUMNS)]
        for point in points:
            lines.append(
                f"{point.address}\t{point.kind.value}\t{point.datatype.value}\t"
                f"{point.raw}\t{point.tag}"
            )
        QApplication.clipboard().setText("\n".join(lines))
        self._status.setText(f"{len(points)} 件をコピーしました。")

    def _next_free_address(
        self, slave, kind: RegisterKind, datatype: ValueKind, start: int
    ) -> int | None:
        step = 2 if datatype == ValueKind.INT32 else 1
        address = start
        while address + step - 1 < REGISTER_COUNT:
            if slave.get_point(address, kind) is None and (
                step == 1 or slave.get_point(address + 1, kind) is None
            ):
                return address
            address += 1
        return None

    def _duplicate_rows(self, rows: list[int]) -> None:
        if not rows or not self._grid_enabled:
            return
        points = [self._row_meta[row] for row in rows if self._row_meta[row] is not None]
        if not points:
            return
        slave = self._registry.get_slave(self._registry.selected_slave_id)
        added = 0
        skipped: list[str] = []
        for point in points:
            step = 2 if point.datatype == ValueKind.INT32 else 1
            new_address = self._next_free_address(
                slave, point.kind, point.datatype, point.address + step
            )
            if new_address is None:
                skipped.append(f"Addr {point.address}（空きアドレスが見つかりません）")
                continue
            slave.upsert_point(
                RegisterPoint(
                    address=new_address,
                    kind=point.kind,
                    datatype=point.datatype,
                    tag=point.tag,
                    raw=point.raw,
                )
            )
            added += 1
        self._draft = None
        self._rebuild_table()
        if added and self._on_change:
            self._on_change()
        if skipped:
            QMessageBox.warning(
                self, "一部失敗しました", f"{added} 件複製しました。\n" + "\n".join(skipped)
            )
        elif added:
            self._status.setText(f"{added} 件複製しました。")

    def _paste_rows(self) -> None:
        if not self._grid_enabled:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        self._import_register_map_text(text, action_label="貼り付け")

    def _import_register_map_file(self) -> None:
        if not self._grid_enabled:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "レジスタマップを取り込み",
            "",
            "CSV/TSV (*.csv *.tsv *.txt);;すべてのファイル (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except OSError as exc:
            QMessageBox.warning(self, "エラー", f"ファイルを読めませんでした: {exc}")
            return
        self._import_register_map_text(text, action_label="取込")

    def _import_register_map_text(self, text: str, *, action_label: str) -> None:
        slave = self._registry.get_slave(self._registry.selected_slave_id)
        added = 0
        errors: list[str] = []
        first_kind: RegisterKind | None = None
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(","))]
            if parts[0].lower() == "addr":
                continue
            try:
                address = int(parts[0])
                if len(parts) >= 4:
                    # Addr, Kind, Datatype, Raw[, Tag]
                    kind = _parse_kind(parts[1])
                    datatype = _parse_datatype(parts[2], kind)
                    raw = int(parts[3])
                    tag = parts[4] if len(parts) > 4 else ""
                elif len(parts) >= 2:
                    # Addr, Raw[, Tag] — 現在の Kind タブに投入
                    kind = self._active_kind
                    datatype = _default_datatype_for(kind)
                    raw = int(parts[1])
                    tag = parts[2] if len(parts) > 2 else ""
                else:
                    raise ValueError("列数が不足しています（Addr/Kind/Datatype/Raw または Addr/Raw）")
                validate_address(address, datatype)
            except ValueError as exc:
                errors.append(f"{line_no}行目: {exc}")
                continue
            slave.upsert_point(
                RegisterPoint(address=address, kind=kind, datatype=datatype, tag=tag, raw=raw)
            )
            if first_kind is None:
                first_kind = kind
            added += 1
        self._draft = None
        if first_kind is not None and first_kind != self._active_kind:
            self.set_active_kind(first_kind)
        else:
            self._rebuild_table()
        if added and self._on_change:
            self._on_change()
        if errors:
            QMessageBox.warning(
                self,
                "一部失敗しました",
                f"{added} 件{action_label}しました。\n以下は失敗しました:\n" + "\n".join(errors[:20]),
            )
        elif added:
            self._status.setText(f"{added} 件{action_label}しました。")
        else:
            self._status.setText(f"{action_label}できる行がありませんでした。")

    def _open_range_add_dialog(self) -> None:
        if not self._grid_enabled:
            return
        dialog = RangeAddDialog(self, default_kind=self._active_kind)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            start, count, kind, datatype, raw, tag_prefix = dialog.values()
        except ValueError as exc:
            QMessageBox.warning(self, "エラー", str(exc))
            return
        step = 2 if datatype == ValueKind.INT32 else 1
        slave = self._registry.get_slave(self._registry.selected_slave_id)
        added = 0
        errors: list[str] = []
        for i in range(count):
            address = start + i * step
            try:
                validate_address(address, datatype)
            except ValueError as exc:
                errors.append(f"Addr {address}: {exc}")
                continue
            tag = f"{tag_prefix}{i}" if tag_prefix else ""
            slave.upsert_point(
                RegisterPoint(address=address, kind=kind, datatype=datatype, tag=tag, raw=raw)
            )
            added += 1
        self._draft = None
        self._rebuild_table()
        if added and self._on_change:
            self._on_change()
        if errors:
            QMessageBox.warning(
                self,
                "一部失敗しました",
                f"{added} 件追加しました。\n以下は失敗しました:\n" + "\n".join(errors[:20]),
            )
        elif added:
            self._status.setText(f"{added} 件追加しました。")

    def _install_shortcuts(self) -> None:
        # PySide6 + Python 3.14 では eventFilter オーバーライドが
        # Wayland 上で再帰クラッシュすることがあるため、QShortcut を使う。
        # Backspace はセル編集と衝突するため Delete のみにする。
        context = Qt.ShortcutContext.WidgetWithChildrenShortcut

        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copy_sc.setContext(context)
        copy_sc.activated.connect(self._shortcut_copy)

        paste_sc = QShortcut(QKeySequence.StandardKey.Paste, self.table)
        paste_sc.setContext(context)
        paste_sc.activated.connect(self._paste_rows)

        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        del_sc.setContext(context)
        del_sc.activated.connect(self._shortcut_delete_rows)

        slave_del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.slave_list)
        slave_del_sc.setContext(context)
        slave_del_sc.activated.connect(self._remove_slave)

    def _shortcut_copy(self) -> None:
        rows = self._selected_data_rows()
        if rows:
            self._copy_rows(rows)

    def _shortcut_delete_rows(self) -> None:
        if not self._grid_enabled:
            return
        rows = self._selected_data_rows()
        if rows:
            self._delete_rows(rows)
