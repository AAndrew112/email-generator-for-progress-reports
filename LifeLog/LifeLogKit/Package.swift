// swift-tools-version:5.9
import PackageDescription

// LifeLogKit holds everything that does not depend on UIKit/SwiftUI:
// the data model, the SQLite store, sync merge rules and exporters.
// It builds on Apple platforms (using the system SQLite3 module) and on
// Linux (using the CSQLite system-library shim) so the core can be tested anywhere.

var kitDependencies: [Target.Dependency] = []
var extraTargets: [Target] = []

#if os(Linux)
extraTargets.append(
    .systemLibrary(name: "CSQLite", path: "Linux/CSQLite", pkgConfig: "sqlite3",
                   providers: [.apt(["libsqlite3-dev"])])
)
kitDependencies.append("CSQLite")
#endif

let package = Package(
    name: "LifeLogKit",
    platforms: [.iOS(.v17), .watchOS(.v10), .macOS(.v14)],
    products: [
        .library(name: "LifeLogKit", targets: ["LifeLogKit"]),
    ],
    targets: extraTargets + [
        .target(name: "LifeLogKit", dependencies: kitDependencies),
        .testTarget(name: "LifeLogKitTests", dependencies: ["LifeLogKit"]),
    ]
)
