# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Parse Step classes and STEPS list from factory test scripts.

Ported from the legacy factory parser.
Accepts raw source code and returns a list of step metadata dicts.
Returns [] instead of raising when no STEPS list is found, so non-Step
scripts still work as regular scripts.
"""

import ast
import re


def class_name_to_sentence(name):
    """Convert CamelCase to 'Camel Case'."""
    a = re.compile(r'([A-Z]+)')
    b = re.compile(r'([A-Z][a-z])')
    c = re.compile(r'\W+')
    return c.sub(' ', b.sub(r' \1', a.sub(r' \1', name))).strip()


def is_step(node):
    """Check if an AST ClassDef extends Step."""
    if not isinstance(node, ast.ClassDef):
        return False
    for base in node.bases:
        if isinstance(base, ast.Name):
            if base.id == 'Step':
                return True
        elif isinstance(base, ast.Attribute):
            if (base.attr == 'Step'
                    and isinstance(base.value, ast.Name)
                    and base.value.id == 'factory'):
                return True
    return False


def find_step_classes(tree):
    return [node for node in tree.body if is_step(node)]


def find_step_list(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (isinstance(target, ast.Name)
                    and target.id == 'STEPS'
                    and isinstance(node.value, ast.List)):
                return node.value
    return None


def find_assign(classdef, name):
    for node in classdef.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    return None
    return None


def get_name(classdef):
    assigned_name = find_assign(classdef, 'DisplayName')
    if assigned_name:
        return assigned_name
    return class_name_to_sentence(classdef.name)


def get_description(classdef):
    return find_assign(classdef, 'Description')


def get_image(classdef):
    return find_assign(classdef, 'Image')


def get_link(classdef):
    return find_assign(classdef, 'Link')


def build_output_steps(step_list, step_classes):
    name_map = {cls.name: cls for cls in step_classes}
    output = []
    for elt in step_list.elts:
        if not isinstance(elt, ast.Name):
            continue
        classdef = name_map.get(elt.id)
        if classdef is None:
            continue
        output.append({
            'class': classdef.name,
            'name': get_name(classdef),
            'description': get_description(classdef),
            'image': get_image(classdef),
            'link': get_link(classdef),
        })
    return output


def parse_code(source_code):
    """Parse source code for Step classes and STEPS list.

    Returns a list of step metadata dicts, or [] if no STEPS found.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    step_classes = find_step_classes(tree)
    step_list = find_step_list(tree)

    if step_list is None or not step_classes:
        return []

    return build_output_steps(step_list, step_classes)
