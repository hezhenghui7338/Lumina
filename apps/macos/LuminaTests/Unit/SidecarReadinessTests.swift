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
}
