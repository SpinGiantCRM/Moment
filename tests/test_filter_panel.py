"""Tests for ui/editor/filter_panel.py — video filter panel."""

from __future__ import annotations

import pytest

from moment.ui.editor.filter_panel import FilterPanel

pytestmark = [pytest.mark.gui]


class TestFilterPanelInit:
    """Tests for FilterPanel construction."""

    def test_create(self, qapp) -> None:

        panel = FilterPanel()
        assert panel is not None
        assert panel._brightness == 0
        assert panel._contrast == 0
        assert panel._saturation == 100

    def test_default_filters_empty(self, qapp) -> None:
        panel = FilterPanel()
        # Defaults (brightness=0, contrast=0, saturation=100) don't produce filters
        assert panel.filters == []

    def test_default_overlays_empty(self, qapp) -> None:
        panel = FilterPanel()
        assert panel.overlays == []

    def test_profile_changed_signal(self, qapp) -> None:
        panel = FilterPanel()
        assert hasattr(panel, "profile_changed")


class TestFilterPanelWidgets:
    """Tests for widget existence."""

    def test_sliders_exist(self, qapp) -> None:
        panel = FilterPanel()
        assert panel._brightness_slider is not None
        assert panel._contrast_slider is not None
        assert panel._saturation_slider is not None
        assert panel._hue_slider is not None

    def test_overlay_buttons_exist(self, qapp) -> None:
        panel = FilterPanel()
        assert panel._overlay_list_label is not None

    def test_crop_combo_exists(self, qapp) -> None:
        panel = FilterPanel()
        assert panel._crop_lock_combo is not None


class TestFilterPanelFilterGeneration:
    """Tests for filter list generation."""

    def test_brightness_nonzero_generates_filter(self, qapp) -> None:
        panel = FilterPanel()
        panel._on_brightness(50)
        filters = panel.filters
        assert len(filters) > 0
        assert any(f.filter_name == "eq" for f in filters)

    def test_hue_nonzero_generates_filter(self, qapp) -> None:
        panel = FilterPanel()
        panel._on_hue(90)
        filters = panel.filters
        assert any(f.filter_name == "hue" for f in filters)

    def test_contrast_adjustment(self, qapp) -> None:
        panel = FilterPanel()
        panel._on_contrast(20)
        assert panel._contrast == 20


class TestFilterPanelEdgeCases:
    """Edge case tests."""

    def test_brightness_negative(self, qapp) -> None:
        panel = FilterPanel()
        panel._on_brightness(-50)
        assert panel._brightness == -50

    def test_set_profile_loads_filters(self, qapp) -> None:
        from moment.core.models import FilterConfig

        panel = FilterPanel()
        panel.set_profile(
            filters=[FilterConfig(filter_name="eq", params={"brightness": 0.5})],
            overlays=[],
        )
        assert panel._brightness == 50
