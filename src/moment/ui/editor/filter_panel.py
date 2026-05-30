"""Filter panel — video filters, overlays, crop, and rotate.

Provides sliders for brightness/contrast/saturation/hue, a before/after
toggle, text/image overlay management, and crop/rotate controls.

All changes are accumulated in :class:`FilterConfig` and
:class:`OverlayConfig` lists and emitted via ``profile_changed``.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from moment.core.models import FilterConfig, OverlayConfig

logger = logging.getLogger(__name__)


class FilterPanel(QWidget):
    """Video filters + overlays + crop/rotate panel.

    Signals:
        profile_changed: Emitted whenever any filter/overlay setting changes.
    """

    profile_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._filters: list[FilterConfig] = []
        self._overlays: list[OverlayConfig] = []

        # Slider values (in percentage units where applicable)
        self._brightness = 0
        self._contrast = 0
        self._saturation = 100
        self._hue = 0
        self._before_after = False

        # Crop state
        self._crop_w: int | None = None
        self._crop_h: int | None = None
        self._crop_x: int = 0
        self._crop_y: int = 0
        self._crop_lock: str = "free"

        # Rotate state
        self._rotate = 0
        self._flip_h = False
        self._flip_v = False

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def filters(self) -> list[FilterConfig]:
        """Return the accumulated filter list."""
        result: list[FilterConfig] = []
        if self._brightness != 0 or self._contrast != 0 or self._saturation != 100:
            result.append(
                FilterConfig(
                    filter_name="eq",
                    params={
                        "brightness": self._brightness / 100.0,
                        "contrast": self._contrast / 100.0 + 1.0,
                        "saturation": self._saturation / 100.0,
                    },
                )
            )
        if self._hue != 0:
            result.append(
                FilterConfig(
                    filter_name="hue",
                    params={"h": self._hue},
                )
            )
        return result

    @property
    def overlays(self) -> list[OverlayConfig]:
        return list(self._overlays)

    def set_profile(
        self,
        filters: list[FilterConfig],
        overlays: list[OverlayConfig],
    ) -> None:
        """Load filter/overlay state from an existing profile."""
        self._filters = list(filters)
        self._overlays = list(overlays)
        for f in filters:
            if f.filter_name == "eq":
                self._brightness = int(f.params.get("brightness", 0) * 100)
                self._contrast = int((f.params.get("contrast", 1.0) - 1.0) * 100)
                self._saturation = int(f.params.get("saturation", 1.0) * 100)
                self._brightness_slider.blockSignals(True)
                self._contrast_slider.blockSignals(True)
                self._saturation_slider.blockSignals(True)
                self._brightness_slider.setValue(self._brightness)
                self._contrast_slider.setValue(self._contrast)
                self._saturation_slider.setValue(self._saturation)
                self._brightness_slider.blockSignals(False)
                self._contrast_slider.blockSignals(False)
                self._saturation_slider.blockSignals(False)
            elif f.filter_name == "hue":
                self._hue = int(f.params.get("h", 0))
                self._hue_slider.blockSignals(True)
                self._hue_slider.setValue(self._hue)
                self._hue_slider.blockSignals(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(16)

        # --- Video adjustments group ---
        adj_group = QGroupBox("Video Adjustments")
        adj_layout = QVBoxLayout(adj_group)
        adj_layout.setSpacing(10)

        # Brightness
        adj_layout.addLayout(
            self._slider_row(
                "Brightness", -100, 100, 0, "%", "_brightness_slider", self._on_brightness
            )
        )

        # Contrast
        adj_layout.addLayout(
            self._slider_row("Contrast", -100, 100, 0, "%", "_contrast_slider", self._on_contrast)
        )

        # Saturation
        adj_layout.addLayout(
            self._slider_row(
                "Saturation", 0, 200, 100, "%", "_saturation_slider", self._on_saturation
            )
        )

        # Hue
        adj_layout.addLayout(
            self._slider_row("Hue", -180, 180, 0, "°", "_hue_slider", self._on_hue)
        )

        # Before/After toggle
        self._before_after_check = QCheckBox("Before / After split view")
        self._before_after_check.toggled.connect(self._on_before_after)
        adj_layout.addWidget(self._before_after_check)

        layout.addWidget(adj_group)

        # --- Overlays group ---
        overlay_group = QGroupBox("Overlays")
        overlay_layout = QVBoxLayout(overlay_group)
        overlay_layout.setSpacing(8)

        # Text overlay row
        text_row = QHBoxLayout()
        text_row.addWidget(QLabel("Text overlay:"))
        text_row.addStretch()
        add_text_btn = QPushButton("Add Text")
        add_text_btn.clicked.connect(self._add_text_overlay)
        text_row.addWidget(add_text_btn)
        overlay_layout.addLayout(text_row)

        # Image overlay row
        img_row = QHBoxLayout()
        img_row.addWidget(QLabel("Image overlay:"))
        img_row.addStretch()
        add_img_btn = QPushButton("Add Image…")
        add_img_btn.clicked.connect(self._add_image_overlay)
        img_row.addWidget(add_img_btn)
        overlay_layout.addLayout(img_row)

        # Overlay list label
        self._overlay_list_label = QLabel("No overlays")
        self._overlay_list_label.setObjectName("cardMeta")
        overlay_layout.addWidget(self._overlay_list_label)

        layout.addWidget(overlay_group)

        # --- Crop / Rotate group ---
        crop_group = QGroupBox("Crop & Rotate")
        crop_layout = QVBoxLayout(crop_group)
        crop_layout.setSpacing(10)

        # Aspect ratio lock
        lock_row = QHBoxLayout()
        lock_row.addWidget(QLabel("Aspect ratio:"))
        self._crop_lock_combo = QComboBox()
        self._crop_lock_combo.addItems(["Free", "16:9", "4:3", "1:1", "21:9"])
        self._crop_lock_combo.currentTextChanged.connect(self._on_crop_lock)
        lock_row.addWidget(self._crop_lock_combo)
        lock_row.addStretch()
        crop_layout.addLayout(lock_row)

        # Preset sizes
        preset_row = QHBoxLayout()
        for label, w, h in [
            ("1920×1080", 1920, 1080), ("1280×720", 1280, 720), ("854×480", 854, 480)
        ]:
            btn = QPushButton(label)
            btn.setFixedSize(88, 28)
            btn.clicked.connect(lambda checked, cw=w, ch=h: self._set_crop_size(cw, ch))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        crop_layout.addLayout(preset_row)

        # Rotate row
        rotate_row = QHBoxLayout()
        rotate_row.addWidget(QLabel("Rotate:"))
        for deg, label in [(0, "0°"), (90, "90°"), (180, "180°"), (270, "270°")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedSize(44, 28)
            if deg == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, d=deg: self._on_rotate(d))
            rotate_row.addWidget(btn)

        # Flip toggles
        self._flip_h_check = QCheckBox("Flip H")
        self._flip_h_check.toggled.connect(self._on_flip_h)
        rotate_row.addWidget(self._flip_h_check)

        self._flip_v_check = QCheckBox("Flip V")
        self._flip_v_check.toggled.connect(self._on_flip_v)
        rotate_row.addWidget(self._flip_v_check)

        rotate_row.addStretch()
        crop_layout.addLayout(rotate_row)

        layout.addWidget(crop_group)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Slider helpers
    # ------------------------------------------------------------------

    def _slider_row(
        self, label: str, lo: int, hi: int, default: int, suffix: str,
        attr_name: str, handler,
    ) -> QHBoxLayout:
        """Build a horizontal row: label | slider | value label."""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(80)
        lbl.setObjectName("cardMeta")
        row.addWidget(lbl)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(default)
        slider.valueChanged.connect(handler)
        row.addWidget(slider, stretch=1)

        val_lbl = QLabel(f"{default}{suffix}")
        val_lbl.setFixedWidth(50)
        val_lbl.setObjectName("cardMeta")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(val_lbl)

        # Store references
        setattr(self, attr_name, slider)
        setattr(self, f"{attr_name}_label", val_lbl)
        setattr(self, f"{attr_name}_suffix", suffix)

        return row

    # ------------------------------------------------------------------
    # Filter handlers
    # ------------------------------------------------------------------

    def _on_brightness(self, value: int) -> None:
        self._brightness = value
        self._brightness_slider_label.setText(f"{value}{self._brightness_slider_suffix}")
        self.profile_changed.emit()

    def _on_contrast(self, value: int) -> None:
        self._contrast = value
        self._contrast_slider_label.setText(f"{value}{self._contrast_slider_suffix}")
        self.profile_changed.emit()

    def _on_saturation(self, value: int) -> None:
        self._saturation = value
        self._saturation_slider_label.setText(f"{value}{self._saturation_slider_suffix}")
        self.profile_changed.emit()

    def _on_hue(self, value: int) -> None:
        self._hue = value
        self._hue_slider_label.setText(f"{value}{self._hue_slider_suffix}")
        self.profile_changed.emit()

    def _on_before_after(self, checked: bool) -> None:
        self._before_after = checked
        self.profile_changed.emit()

    # ------------------------------------------------------------------
    # Overlay handlers
    # ------------------------------------------------------------------

    def _add_text_overlay(self) -> None:
        """Add a default text overlay."""
        overlay = OverlayConfig(
            overlay_type="text",
            content="Your text here",
            position_x=0.5,
            position_y=0.1,
            start_time=0.0,
            end_time=None,
        )
        self._overlays.append(overlay)
        self._update_overlay_label()
        self.profile_changed.emit()

    def _add_image_overlay(self) -> None:
        """Add an image overlay via file picker."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image Overlay", "",
            "PNG Images (*.png);;All Files (*)",
        )
        if not path:
            return
        overlay = OverlayConfig(
            overlay_type="image",
            content=path,
            position_x=0.5,
            position_y=0.5,
            width=0.2,
            height=None,
            start_time=0.0,
            end_time=None,
        )
        self._overlays.append(overlay)
        self._update_overlay_label()
        self.profile_changed.emit()

    def _update_overlay_label(self) -> None:
        count = len(self._overlays)
        self._overlay_list_label.setText(
            f"{count} overlay{'s' if count != 1 else ''} added"
        )

    # ------------------------------------------------------------------
    # Crop / Rotate handlers
    # ------------------------------------------------------------------

    def _on_crop_lock(self, text: str) -> None:
        self._crop_lock = text.lower().replace(":", "_")
        self.profile_changed.emit()

    def _set_crop_size(self, w: int, h: int) -> None:
        self._crop_w = w
        self._crop_h = h
        self.profile_changed.emit()

    def _on_rotate(self, deg: int) -> None:
        self._rotate = deg
        self.profile_changed.emit()

    def _on_flip_h(self, checked: bool) -> None:
        self._flip_h = checked
        self.profile_changed.emit()

    def _on_flip_v(self, checked: bool) -> None:
        self._flip_v = checked
        self.profile_changed.emit()
