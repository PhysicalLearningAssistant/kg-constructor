"""ID 生成与常用术语映射。"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# 常见电磁学术语 → 语义化英文 ID；未收录的术语回退到 kp_<hash>。
KNOWN_NODE_IDS: dict[str, str] = {
    "电荷": "electric_charge",
    "点电荷": "point_charge",
    "试探电荷": "test_charge",
    "库仑定律": "coulomb_law",
    "电场": "electric_field",
    "电场强度": "electric_field",
    "电场线": "electric_field_line",
    "电通量": "electric_flux",
    "高斯定理": "gauss_law",
    "高斯定律": "gauss_law",
    "高斯面": "gaussian_surface",
    "高斯面法": "gauss_surface_method",
    "对称性分析": "symmetry_analysis",
    "均匀带电球面的电场": "uniform_sphere_field",
    "无限长带电直线的电场": "infinite_line_field",
    "无限大带电平面的电场": "infinite_plane_field",
    "静电屏蔽": "electrostatic_shielding",
    "电势": "electric_potential",
    "电势差": "potential_difference",
    "电容": "capacitance",
    "电偶极子": "electric_dipole",
    "磁感应强度": "magnetic_field",
    "磁通量": "magnetic_flux",
    "磁感线": "magnetic_field_line",
    "安培环路定理": "ampere_law",
    "安培环路定律": "ampere_law",
    "法拉第电磁感应定律": "faraday_law",
    "法拉第定律": "faraday_law",
    "麦克斯韦方程组": "maxwell_equations",
    "电动势": "electromotive_force",
    "洛伦兹力": "lorentz_force",
    "位移电流": "displacement_current",
    "电磁波": "electromagnetic_wave",
    "叠加法": "superposition_method",
    "镜像法": "image_method",
    "电荷量": "charge_quantity",
    "电场力": "electric_force",
    "真空介电常数": "vacuum_permittivity",
    "真空磁导率": "vacuum_permeability",
    "楞次定律": "lenz_law",
    "高斯磁定律": "gauss_magnetic_law",
    "安培-麦克斯韦定律": "ampere_maxwell_law",
}

KNOWN_CHAPTER_IDS: dict[str, str] = {
    "静电场": "ch_electrostatics",
    "恒定磁场": "ch_steady_magnetic_field",
    "电磁感应": "ch_electromagnetic_induction",
    "电磁感应与麦克斯韦方程组": "ch_electromagnetic_induction",
    "麦克斯韦方程组": "ch_maxwell_equations",
}

_ASCII_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
)


def normalize_name(value: str) -> str:
    """名称规范化：NFC、压空白、去首尾空白、ASCII 转小写。"""

    normalized = unicodedata.normalize("NFC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.translate(_ASCII_MAP)


def node_id(name: str, used: set[str]) -> str:
    """为节点生成合法且唯一的 ID。"""

    key = KNOWN_NODE_IDS.get(name)
    if key is None:
        digest = hashlib.sha1(normalize_name(name).encode("utf-8")).hexdigest()[:8]
        key = f"kp_{digest}"
    candidate = key
    suffix = 2
    while candidate in used:
        candidate = f"{key}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def chapter_id(title: str, parent_id: str | None, sibling_index: int, used: set[str]) -> str:
    """为章节生成合法且唯一的 ID。"""

    key = KNOWN_CHAPTER_IDS.get(title)
    if key is None:
        if parent_id:
            key = f"{parent_id}_s{sibling_index + 1}"
        else:
            key = f"ch_{sibling_index + 1:03d}"
    candidate = key
    suffix = 2
    while candidate in used:
        candidate = f"{key}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
