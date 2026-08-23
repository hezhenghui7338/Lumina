import XCTest
@testable import Lumina

/// E2E-BOOT-02: Sidecar startup readiness and connection error mapping.
final class SidecarReadinessTests: XCTestCase {
    func testConnectionError_detectsCannotConnectToHost() {
        let error = URLError(.cannotConnectToHost)
        XCTAssertTrue(ConnectionError.isConnectionFailure(error))
    }

    func testConnectionError_ignoresDecodingErrors() {
        struct Bad: Decodable {}
        let data = Data("{}".utf8)
        let error: Error
        do {
            _ = try JSONDecoder().decode(Bad.self, from: data)
            XCTFail("expected decode error")
            return
        } catch let caught {
            error = caught
        }
        XCTAssertFalse(ConnectionError.isConnectionFailure(error))
    }

    func testConnectionError_userMessageUsesChineseFallback() {
        let error = URLError(.cannotConnectToHost)
        let message = ConnectionError.userMessage(for: error)
        XCTAssertEqual(message, "无法连接到 AI 引擎，请重试。")
        XCTAssertFalse(message.contains("Could not connect"))
    }

    func testConnectionError_userMessagePreservesNonConnectionErrors() {
        let error = NSError(domain: "CoreClient", code: 500, userInfo: [
            NSLocalizedDescriptionKey: "服务器内部错误",
        ])
        XCTAssertEqual(ConnectionError.userMessage(for: error), "服务器内部错误")
    }

    func testSidecarReadiness_shouldInvokeEnsureRunningWhenBootstrapNeverStarted() {
        XCTAssertTrue(
            SidecarReadiness.shouldInvokeEnsureRunning(
                isRunning: false,
                isBootstrapping: false,
                launchError: nil,
                sawBootstrapStart: false
            )
        )
    }

    func testSidecarReadiness_shouldNotInvokeWhenAlreadyRunning() {
        XCTAssertFalse(
            SidecarReadiness.shouldInvokeEnsureRunning(
                isRunning: true,
                isBootstrapping: false,
                launchError: nil,
                sawBootstrapStart: false
            )
        )
    }

    func testSidecarReadiness_shouldNotInvokeWhenBootstrapping() {
        XCTAssertFalse(
            SidecarReadiness.shouldInvokeEnsureRunning(
                isRunning: false,
                isBootstrapping: true,
                launchError: nil,
                sawBootstrapStart: false
            )
        )
    }

    func testSidecarReadiness_isReadyRequiresRunningWithoutError() {
        XCTAssertTrue(SidecarReadiness.isReady(isRunning: true, launchError: nil))
        XCTAssertFalse(SidecarReadiness.isReady(isRunning: false, launchError: nil))
        XCTAssertFalse(SidecarReadiness.isReady(isRunning: true, launchError: "failed"))
    }

    func testCompatibleHandshake_requiresChunkerAndCoreVersion() {
        XCTAssertTrue(
            SidecarReadiness.isCompatible(
                chunkerVersion: SidecarReadiness.expectedChunkerVersion,
                coreVersion: "0.8.1",
                expectedCoreVersion: "0.8.1"
            )
        )
        XCTAssertFalse(
            SidecarReadiness.isCompatible(
                chunkerVersion: "7",
                coreVersion: "0.8.1",
                expectedCoreVersion: "0.8.1"
            )
        )
        XCTAssertFalse(
            SidecarReadiness.isCompatible(
                chunkerVersion: SidecarReadiness.expectedChunkerVersion,
                coreVersion: "0.8.0",
                expectedCoreVersion: "0.8.1"
            )
        )
        XCTAssertFalse(
            SidecarReadiness.isCompatible(
                chunkerVersion: SidecarReadiness.expectedChunkerVersion,
                coreVersion: nil,
                expectedCoreVersion: "0.8.1"
            )
        )
    }

    func testShouldReplaceOrphan_whenCoreVersionDiffers() {
        XCTAssertTrue(
            replaceOrphan(
                coreVersion: "0.8.0",
                expectedCoreVersion: "0.8.1",
                hasBundledSidecar: true,
                orphanExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                bundledExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                orphanStartedAt: Date(timeIntervalSince1970: 200),
                bundledModifiedAt: Date(timeIntervalSince1970: 100)
            )
        )
    }

    func testShouldReplaceOrphan_whenBundledBinaryIsNewer() {
        XCTAssertTrue(
            replaceOrphan(
                coreVersion: "0.8.1",
                expectedCoreVersion: "0.8.1",
                hasBundledSidecar: true,
                orphanExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                bundledExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                orphanStartedAt: Date(timeIntervalSince1970: 100),
                bundledModifiedAt: Date(timeIntervalSince1970: 200)
            )
        )
    }

    func testShouldReplaceOrphan_keepsSameBuild() {
        XCTAssertFalse(
            replaceOrphan(
                coreVersion: "0.8.1",
                expectedCoreVersion: "0.8.1",
                hasBundledSidecar: true,
                orphanExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                bundledExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                orphanStartedAt: Date(timeIntervalSince1970: 200),
                bundledModifiedAt: Date(timeIntervalSince1970: 100)
            )
        )
    }

    func testShouldReplaceOrphan_debugReusesCompatibleUvSidecar() {
        XCTAssertFalse(
            replaceOrphan(
                coreVersion: "0.8.1",
                expectedCoreVersion: "0.8.1",
                hasBundledSidecar: false,
                orphanExecutable: "/Users/dev/.local/share/uv/python",
                bundledExecutable: nil,
                orphanStartedAt: Date(timeIntervalSince1970: 50),
                bundledModifiedAt: nil
            )
        )
    }

    func testShouldReplaceOrphan_debugReplacesLeftoverFrozenSidecar() {
        XCTAssertTrue(
            replaceOrphan(
                coreVersion: "0.8.1",
                expectedCoreVersion: "0.8.1",
                hasBundledSidecar: false,
                orphanExecutable: "/dist/Lumina.app/Contents/Resources/lumina-core/lumina-core",
                bundledExecutable: nil,
                orphanStartedAt: Date(timeIntervalSince1970: 50),
                bundledModifiedAt: nil
            )
        )
    }

    func testShouldReplaceOrphan_legacyHealthWithoutCoreVersion() {
        XCTAssertTrue(
            replaceOrphan(
                coreVersion: nil,
                expectedCoreVersion: "0.8.1",
                hasBundledSidecar: true,
                orphanExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                bundledExecutable: "/app/Contents/Resources/lumina-core/lumina-core",
                orphanStartedAt: Date(timeIntervalSince1970: 200),
                bundledModifiedAt: Date(timeIntervalSince1970: 100)
            )
        )
    }

    private func replaceOrphan(
        coreVersion: String?,
        expectedCoreVersion: String,
        hasBundledSidecar: Bool,
        orphanExecutable: String?,
        bundledExecutable: String?,
        orphanStartedAt: Date?,
        bundledModifiedAt: Date?
    ) -> Bool {
        SidecarReadiness.shouldReplaceOrphan(
            chunkerVersion: SidecarReadiness.expectedChunkerVersion,
            coreVersion: coreVersion,
            expectedCoreVersion: expectedCoreVersion,
            hasBundledSidecar: hasBundledSidecar,
            orphanExecutable: orphanExecutable,
            bundledExecutable: bundledExecutable,
            orphanStartedAt: orphanStartedAt,
            bundledModifiedAt: bundledModifiedAt
        )
    }
}
