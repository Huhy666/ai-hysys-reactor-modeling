import contextlib
from typing import Any


def collect_member_names(value: Any) -> list[str]:
    """Collect static and late-bound pywin32 COM member names safely."""
    names = {name for name in dir(value) if not name.startswith("_")}
    for map_name in ("_prop_map_get_", "_prop_map_put_", "_olerepr_"):
        mapping = getattr(value, map_name, None)
        if isinstance(mapping, dict):
            names.update(str(name) for name in mapping)
    return sorted(names)


def collect_reactor_control_properties(value: Any) -> dict[str, Any]:
    """Read actual V15 control names and metadata without changing reactor state."""
    names = set(collect_member_names(value))
    with contextlib.suppress(Exception):
        names.update(_collect_type_info_member_names(value._oleobj_.GetTypeInfo()))
    controls = {}
    for name in sorted(names):
        if not any(word in name.casefold() for word in ("separat", "ignore", "solve")):
            continue
        entry = {"metadata": collect_member_signature(value, name)}
        try:
            current = getattr(value, name)
            if current is None or isinstance(current, (bool, int, float, str)):
                entry["value"] = current
            else:
                entry["value_type"] = type(current).__name__
        except Exception as exc:
            entry["read_error"] = f"{type(exc).__name__}: {exc}"
        controls[name] = entry
    return controls


def collect_member_signature(value: Any, member_name: str) -> dict[str, Any]:
    """Read a late-bound COM method signature without invoking the method."""
    try:
        dispatch = value._oleobj_
        dispid = dispatch.GetIDsOfNames(member_name)
        if isinstance(dispid, (tuple, list)):
            dispid = dispid[0]
        type_info = dispatch.GetTypeInfo()
        names = list(type_info.GetNames(dispid))
        documentation = type_info.GetDocumentation(dispid)
    except Exception as exc:
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "available": True,
        "dispid": dispid,
        "member": names[0] if names else member_name,
        "parameters": names[1:],
        "documentation": str(documentation[1] or ""),
    }


def _collect_type_info_member_names(type_info: Any, limit: int = 256) -> list[str]:
    names: set[str] = set()
    for descriptor_getter_name in ("GetFuncDesc", "GetVarDesc"):
        descriptor_getter = getattr(type_info, descriptor_getter_name)
        for index in range(limit):
            try:
                descriptor = descriptor_getter(index)
            except Exception:
                break
            with contextlib.suppress(Exception):
                member_names = type_info.GetNames(descriptor[0])
                if member_names:
                    names.add(str(member_names[0]))
    return sorted(names)


def collect_type_library_matches(
    value: Any,
    keywords: tuple[str, ...],
) -> dict[str, Any]:
    """Return COM type-library names relevant to the supplied keywords."""
    try:
        root_type_info = value._oleobj_.GetTypeInfo()
        type_library, _ = root_type_info.GetContainingTypeLib()
        library_name = str(type_library.GetDocumentation(-1)[0])
        type_count = int(type_library.GetTypeInfoCount())
    except Exception as exc:
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "types": [],
        }

    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    matches = []
    for index in range(type_count):
        try:
            type_name = str(type_library.GetDocumentation(index)[0])
            type_info = type_library.GetTypeInfo(index)
            type_kind = int(type_library.GetTypeInfoType(index))
            members = _collect_type_info_member_names(type_info)
        except Exception:
            continue
        searchable = (type_name, *members)
        if not any(
            keyword in candidate.lower()
            for keyword in lowered_keywords
            for candidate in searchable
        ):
            continue
        matches.append(
            {
                "name": type_name,
                "type_kind": type_kind,
                "members": members,
            }
        )
    return {
        "available": True,
        "library": library_name,
        "types": matches,
    }


def try_create_named_object(
    operations: Any,
    type_names: list[str],
    operation_name: str,
) -> tuple[Any | None, dict[str, Any]]:
    errors = []
    call_shapes = (
        ("type_then_name", lambda type_name: (type_name, operation_name)),
        ("name_then_type", lambda type_name: (operation_name, type_name)),
    )
    for argument_order, build_arguments in call_shapes:
        for type_name in type_names:
            try:
                operation = operations.Add(*build_arguments(type_name))
            except Exception as exc:
                errors.append(
                    {
                        "type_name": type_name,
                        "argument_order": argument_order,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            return operation, {
                "success": True,
                "type_name": type_name,
                "argument_order": argument_order,
                "object_name": str(getattr(operation, "name", "")),
                "object_type_name": str(getattr(operation, "TypeName", "")),
                "visible_type_name": str(getattr(operation, "VisibleTypeName", "")),
                "members": collect_member_names(operation),
                "errors": errors,
            }
    return None, {
        "success": False,
        "type_name": None,
        "argument_order": None,
        "object_name": None,
        "object_type_name": None,
        "visible_type_name": None,
        "members": [],
        "errors": errors,
    }


def try_add_operation(
    operations: Any,
    type_names: list[str],
    operation_name: str,
) -> dict[str, Any]:
    _, report = try_create_named_object(operations, type_names, operation_name)
    return report
