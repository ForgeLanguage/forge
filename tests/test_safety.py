import unittest

from forge_safety import SafetyCheckError, check_safety
from forge_typecheck import check_types
from forge_parser import parse


class SafetyCheckTests(unittest.TestCase):
    def test_marks_owner_as_terminated_after_terminate_call(self) -> None:
        program = parse(
            """
class File {
    exclusive terminate dispose(): Void {}
}

main(): Void {
    var file: File
    file.dispose()
}
"""
        )

        result = check_safety(program)
        file_declaration = program.declarations[1].body.statements[0]
        file_symbol = result.typecheck.resolution.analysis.annotations.symbol_for(file_declaration)

        self.assertEqual(result.safety.state_of_symbol(file_symbol).ownership, "owner")
        self.assertEqual(result.safety.state_of_symbol(file_symbol).availability, "terminated")

    def test_reports_use_after_terminate(self) -> None:
        program = parse(
            """
class File {
    exclusive terminate dispose(): Void {}
}

main(): Void {
    var file: File
    file.dispose()
    file.dispose()
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot use terminated resource 'file'", messages)
        self.assertIn("Cannot call method 'dispose' after resource was terminated", messages)

    def test_borrow_is_invalidated_when_owner_terminates(self) -> None:
        program = parse(
            """
class File {
    exclusive terminate dispose(): Void {}
}

main(): Void {
    var file: File
    const borrowed: File = file
    file.dispose()
    borrowed.dispose()
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn(
            "Cannot use borrow 'borrowed' after owner 'file' was terminated",
            messages,
        )

    def test_reports_exclusive_call_through_borrow(self) -> None:
        program = parse(
            """
class File {
    exclusive flush(): Void {}
}

main(): Void {
    var file: File
    const borrowed: File = file
    borrowed.flush()
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot call exclusive method 'flush' through borrow",
        )

    def test_reports_use_after_move(self) -> None:
        program = parse(
            """
class Profile {}
consume(take profile: Profile): Void {}

main(): Void {
    var profile: Profile
    consume(move profile)
    const copy: Profile = profile
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot use moved resource 'profile'", messages)

    def test_rejects_moving_borrowed_parameter(self) -> None:
        program = parse(
            """
class Profile {}
consume(take profile: Profile): Void {}

passOn(profile: Profile): Void {
    consume(move profile)
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot move borrowed resource 'profile'",
        )

    def test_allows_move_of_owned_call_result(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public take profile: Profile
    public new(take profile: Profile) {
        this.profile = move profile
    }
}
makeProfile(): Profile => Profile.new()
const user = User.new(move makeProfile())
"""
        )

        result = check_safety(program)

        self.assertTrue(result.ok)

    def test_rejects_move_of_borrowed_call_result(self) -> None:
        program = parse(
            """
class Profile {}
borrow borrowed(profile: Profile): Profile => profile
consume(take profile: Profile): Void {}
main(): Void {
    var profile: Profile
    consume(move borrowed(profile))
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot move borrowed return value",
        )

    def test_field_assignment_consumes_owned_local(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile?
    public setProfile(take profile: Profile): Void {
        this.profile = profile
        const copy: Profile = profile
    }
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot use moved resource 'profile'", messages)

    def test_owned_local_field_assignment_requires_move(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile?
}

main(): Void {
    var user: User
    var profile: Profile
    user.profile = profile
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Assigning owned resource 'profile' to owned field requires 'move'",
        )

    def test_owned_local_field_assignment_with_move_consumes_local(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile?
}

main(): Void {
    var user: User
    var profile: Profile
    user.profile = move profile
}
"""
        )

        result = check_safety(program)
        profile_declaration = program.declarations[2].body.statements[1]
        profile_symbol = result.typecheck.resolution.analysis.annotations.symbol_for(
            profile_declaration
        )

        self.assertEqual(result.safety.state_of_symbol(profile_symbol).availability, "moved")

    def test_owned_local_reassignment_requires_move(self) -> None:
        program = parse(
            """
class Profile {}
main(): Void {
    var first: Profile
    var second: Profile
    first = second
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Assigning owned resource 'second' to owned local requires 'move'",
        )

    def test_owned_local_reassignment_with_move_consumes_source(self) -> None:
        program = parse(
            """
class Profile {}
main(): Void {
    var first: Profile
    var second: Profile
    first = move second
}
"""
        )

        result = check_safety(program)
        second_declaration = program.declarations[1].body.statements[1]
        second_symbol = result.typecheck.resolution.analysis.annotations.symbol_for(
            second_declaration
        )

        self.assertEqual(result.safety.state_of_symbol(second_symbol).availability, "moved")

    def test_rejects_borrowed_resource_assigned_to_owned_local(self) -> None:
        program = parse(
            """
class Profile {}
set(first: Profile): Void {
    var second: Profile
    second = first
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot assign borrowed resource 'first' to owned local",
        )

    def test_requires_constructor_to_initialize_non_nullable_owned_field(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile
    public new() {}
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Owned field 'profile' must be initialized by constructor",
        )

    def test_default_constructor_fails_for_non_nullable_owned_field(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Owned field 'profile' must be initialized by constructor",
        )

    def test_allows_constructor_initialized_non_nullable_owned_field(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile
    public new(take profile: Profile) {
        this.profile = profile
    }
}
"""
        )

        result = check_safety(program)

        self.assertTrue(result.ok)

    def test_nullable_owned_field_does_not_require_constructor_initialization(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile?
}
"""
        )

        result = check_safety(program)

        self.assertTrue(result.ok)

    def test_rejects_borrowed_resource_assigned_to_owned_field(self) -> None:
        program = parse(
            """
@multidef
class Profile {}
class User {
    public profile: Profile?
    public setProfile(profile: Profile): Void {
        this.profile = profile
    }
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot assign borrowed resource 'profile' to owned field",
        )

    def test_owned_return_consumes_take_parameter(self) -> None:
        program = parse(
            """
class Profile {}
identity(take profile: Profile): Profile {
    return profile
}
"""
        )

        result = check_safety(program)
        profile_parameter = program.declarations[1].parameters[0]
        profile_symbol = result.typecheck.resolution.analysis.annotations.symbol_for(
            profile_parameter
        )

        self.assertEqual(result.safety.state_of_symbol(profile_symbol).availability, "moved")

    def test_owned_local_return_requires_move(self) -> None:
        program = parse(
            """
class Profile {}
makeProfile(): Profile {
    var profile: Profile
    return profile
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Returning owned resource 'profile' requires 'move'",
        )

    def test_owned_local_return_with_move_consumes_local(self) -> None:
        program = parse(
            """
class Profile {}
makeProfile(): Profile {
    var profile: Profile
    return move profile
}
"""
        )

        result = check_safety(program)
        profile_declaration = program.declarations[1].body.statements[0]
        profile_symbol = result.typecheck.resolution.analysis.annotations.symbol_for(
            profile_declaration
        )

        self.assertEqual(result.safety.state_of_symbol(profile_symbol).availability, "moved")

    def test_conditional_move_without_return_invalidates_after_if(self) -> None:
        program = parse(
            """
@multidef
class Profile {
    public name: String
}
class User {
    public profile: Profile?
}

update(flag: Bool): Void {
    var user: User
    var profile: Profile
    if flag {
        user.profile = move profile
    }
    print profile.name
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertIn("Cannot use moved resource 'profile'", messages)

    def test_returning_move_branch_keeps_continuing_branch_available(self) -> None:
        program = parse(
            """
class Profile {
    public name: String
}

choose(flag: Bool): Profile {
    var profile: Profile
    if flag {
        return move profile
    }
    print profile.name
    return move profile
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        messages = [diagnostic.message for diagnostic in result.diagnostics]
        self.assertNotIn("Cannot use moved resource 'profile'", messages)
        self.assertTrue(result.ok)

    def test_rejects_borrowed_resource_returned_as_owned(self) -> None:
        program = parse(
            """
class Profile {}
identity(profile: Profile): Profile {
    return profile
}
"""
        )

        result = check_safety(program, raise_on_error=False)

        self.assertEqual(
            result.diagnostics[0].message,
            "Cannot return borrowed resource 'profile' as owned value",
        )

    def test_allows_non_exclusive_call_through_borrow(self) -> None:
        program = parse(
            """
class File {
    name(): String => "log.txt"
}

main(): Void {
    var file: File
    const borrowed: File = file
    borrowed.name()
}
"""
        )

        result = check_safety(program)

        self.assertTrue(result.ok)

    def test_reports_duplicate_terminate_methods(self) -> None:
        program = parse(
            """
class File {
    exclusive terminate close(): Void {}
    exclusive terminate dispose(): Void {}
}
"""
        )

        with self.assertRaises(SafetyCheckError) as raised:
            check_safety(program)

        self.assertEqual(
            raised.exception.diagnostics[0].message,
            "Class can declare at most one terminate method",
        )

    def test_accepts_typecheck_result(self) -> None:
        program = parse(
            """
class File {}
main(): Void {
    var file: File
}
"""
        )

        typecheck = check_types(program)
        result = check_safety(typecheck)

        self.assertTrue(result.ok)

    def test_loop_result_rejects_borrowed_resource_escape(self) -> None:
        result = check_safety(
            parse(
                """
class File {}

pick(file: File): File? {
    return while true {
        break file
    }
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "Cannot produce owned loop result from borrowed resource 'file'",
            [diagnostic.message for diagnostic in result.diagnostics],
        )

    def test_loop_result_accepts_take_parameter_transfer(self) -> None:
        result = check_safety(
            parse(
                """
class File {}

pick(take file: File): File? {
    return while true {
        break file
    }
}
"""
            )
        )

        self.assertTrue(result.ok)

    def test_loop_fallback_rejects_borrowed_resource_escape(self) -> None:
        result = check_safety(
            parse(
                """
class File {}

pick(file: File): File? {
    return while false {
        break null
    } else file
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "Cannot produce owned loop result from borrowed resource 'file'",
            [diagnostic.message for diagnostic in result.diagnostics],
        )

    def test_loop_conditional_result_accepts_take_parameter_transfer(self) -> None:
        result = check_safety(
            parse(
                """
class File {}

pick(flag: Bool, take first: File, take second: File): File? {
    return while false {
        break null
    } else (flag ? first : second)
}
"""
            )
        )

        self.assertTrue(result.ok)

    def test_loop_result_rejects_borrowed_resource_member(self) -> None:
        result = check_safety(
            parse(
                """
class File {}
class Holder {
    public new(public file: File) {}
}

pick(holder: Holder): File? {
    return while false {
        break null
    } else holder.file
}
"""
            ),
            raise_on_error=False,
        )

        self.assertIn(
            "Cannot produce owned loop result from a borrowed resource member",
            [diagnostic.message for diagnostic in result.diagnostics],
        )


    def test_array_destructuring_borrows_resource_elements(self) -> None:
        program = parse(
            """
class File {}
main(files: File[]): Void {
    const [first] = catch files {
        issue: PatternMismatch => { return }
    }
}
"""
        )

        result = check_safety(program)
        declaration = program.declarations[1].body.statements[0]
        binding = declaration.bindings[0]
        symbol = result.typecheck.resolution.analysis.annotations.symbol_for(binding)

        self.assertEqual(result.safety.state_of_symbol(symbol).ownership, "borrow")


if __name__ == "__main__":
    unittest.main()
