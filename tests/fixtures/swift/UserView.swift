import SwiftUI

/// A user view.
struct UserView: View {
    @State private var count = 0

    var body: some View {
        Text("Hello")
    }

    func handleTap() {}
}

class UserService {
    func fetch() async throws -> User {
        return User()
    }

    @objc func legacyMethod() {}
}

protocol UserRepository {
    func find(id: Int) -> User?
}

enum Status {
    case active
    case inactive
}

extension String {
    func reversed() -> String { return "" }
}

func helper() -> Int { return 0 }
