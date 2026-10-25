import app.hysys.introspection as introspection


class FakeComObject:
    _prop_map_get_ = {"ReactionPackage": object(), "Flowsheet": object()}
    _prop_map_put_ = {"Visible": object()}

    def Save(self):
        return None


class FakeOperations:
    def __init__(self):
        self.attempts = []

    def Add(self, type_name, name):
        self.attempts.append((type_name, name))
        if type_name != "conversionreactorop":
            raise RuntimeError("unsupported type")
        return FakeComObject()


class FakeReverseOperations:
    def __init__(self):
        self.attempts = []

    def Add(self, first, second=None):
        self.attempts.append((first, second))
        if first == "Probe Reactor" and second == "conversionreactorop":
            return FakeComObject()
        raise RuntimeError("unsupported call shape")


class FakeTypeInfo:
    def GetNames(self, dispid):
        assert dispid == 42
        return ("Add", "Name", "OperationType")

    def GetDocumentation(self, dispid):
        assert dispid == 42
        return ("Add", "Adds a flowsheet operation", 0, "")


class FakeOleObject:
    def GetIDsOfNames(self, name):
        assert name == "Add"
        return 42

    def GetTypeInfo(self):
        return FakeTypeInfo()


class FakeTypedComObject:
    _oleobj_ = FakeOleObject()


class FakeLibraryTypeInfo:
    def __init__(self, function_names=(), variable_names=()):
        self.function_names = function_names
        self.variable_names = variable_names

    def GetFuncDesc(self, index):
        if index >= len(self.function_names):
            raise IndexError(index)
        return (100 + index,)

    def GetVarDesc(self, index):
        if index >= len(self.variable_names):
            raise IndexError(index)
        return (200 + index,)

    def GetNames(self, dispid):
        if dispid >= 200:
            return (self.variable_names[dispid - 200],)
        return (self.function_names[dispid - 100],)


class FakeTypeLibrary:
    names = ("HeatExchangerOp", "ConversionReactorOp", "ReactionTypeEnum")
    infos = (
        FakeLibraryTypeInfo(("Duty",)),
        FakeLibraryTypeInfo(("ReactionSet", "Feeds")),
        FakeLibraryTypeInfo(variable_names=("ConversionRxn", "EquilibriumRxn")),
    )

    def GetDocumentation(self, index):
        if index == -1:
            return ("HYSYS Type Library", "", 0, "")
        return (self.names[index], "", 0, "")

    def GetTypeInfoCount(self):
        return len(self.infos)

    def GetTypeInfo(self, index):
        return self.infos[index]

    def GetTypeInfoType(self, index):
        return (5, 5, 0)[index]


class FakeRootTypeInfo:
    def GetContainingTypeLib(self):
        return (FakeTypeLibrary(), 0)


class FakeLibraryOleObject:
    def GetTypeInfo(self):
        return FakeRootTypeInfo()


class FakeLibraryComObject:
    _oleobj_ = FakeLibraryOleObject()


def test_collect_member_names_includes_dynamic_com_property_maps():
    names = introspection.collect_member_names(FakeComObject())

    assert {"Flowsheet", "ReactionPackage", "Save", "Visible"} <= set(names)


def test_try_add_operation_returns_first_success_and_diagnostics():
    operations = FakeOperations()

    result = introspection.try_add_operation(
        operations,
        ["wrong-type", "conversionreactorop", "never-tried"],
        "Probe Reactor",
    )

    assert result["success"] is True
    assert result["type_name"] == "conversionreactorop"
    assert result["argument_order"] == "type_then_name"
    assert operations.attempts == [
        ("wrong-type", "Probe Reactor"),
        ("conversionreactorop", "Probe Reactor"),
    ]
    assert result["errors"][0]["type_name"] == "wrong-type"
    assert "Save" in result["members"]


def test_try_add_operation_falls_back_to_name_then_type_signature():
    operations = FakeReverseOperations()

    result = introspection.try_add_operation(
        operations,
        ["conversionreactorop"],
        "Probe Reactor",
    )

    assert result["success"] is True
    assert result["type_name"] == "conversionreactorop"
    assert result["argument_order"] == "name_then_type"
    assert operations.attempts == [
        ("conversionreactorop", "Probe Reactor"),
        ("Probe Reactor", "conversionreactorop"),
    ]


def test_try_create_named_object_returns_created_com_object_and_identity():
    operations = FakeReverseOperations()

    created, report = introspection.try_create_named_object(
        operations,
        ["conversionreactorop"],
        "Probe Reactor",
    )

    assert isinstance(created, FakeComObject)
    assert report["success"] is True
    assert report["argument_order"] == "name_then_type"
    assert report["object_name"] == ""
    assert report["object_type_name"] == ""


def test_collect_member_signature_reports_parameter_names_from_type_info():
    signature = introspection.collect_member_signature(FakeTypedComObject(), "Add")

    assert signature == {
        "available": True,
        "dispid": 42,
        "member": "Add",
        "parameters": ["Name", "OperationType"],
        "documentation": "Adds a flowsheet operation",
    }


def test_collect_type_library_matches_finds_types_and_enum_members():
    report = introspection.collect_type_library_matches(
        FakeLibraryComObject(),
        ("reactor", "rxn"),
    )

    assert report == {
        "available": True,
        "library": "HYSYS Type Library",
        "types": [
            {
                "name": "ConversionReactorOp",
                "type_kind": 5,
                "members": ["Feeds", "ReactionSet"],
            },
            {
                "name": "ReactionTypeEnum",
                "type_kind": 0,
                "members": ["ConversionRxn", "EquilibriumRxn"],
            },
        ],
    }
