"""Heading and landmark role classification."""

from __future__ import annotations

from lumina_core.chunker.roles import DocumentRole, classify_heading, landmark_role, role_families_differ


def test_classify_heading_front_and_body():
    assert classify_heading("序言") is DocumentRole.PREFACE
    assert classify_heading("## [§卷首]") is DocumentRole.FRONT
    assert classify_heading("译者序") is DocumentRole.PREFACE
    assert classify_heading("楔子") is DocumentRole.PROLOGUE
    assert classify_heading("第一章") is DocumentRole.BODYMATTER
    assert classify_heading("第七章初始") is DocumentRole.BODYMATTER
    assert classify_heading("Chapter 2") is DocumentRole.BODYMATTER
    assert classify_heading("目录") is DocumentRole.TOC
    assert classify_heading("后记") is DocumentRole.EPILOGUE


def test_landmark_role_maps_epub_types():
    assert landmark_role("preface") is DocumentRole.PREFACE
    assert landmark_role("bodymatter") is DocumentRole.BODYMATTER
    assert landmark_role("text") is DocumentRole.BODYMATTER
    assert landmark_role("toc") is DocumentRole.TOC
    assert landmark_role("unknown-type") is None


def test_role_families_differ_preface_vs_body():
    assert role_families_differ(DocumentRole.PREFACE, DocumentRole.BODYMATTER)
    assert not role_families_differ(DocumentRole.COPYRIGHT, DocumentRole.DEDICATION)
