import Foundation

enum ConnectionError {
    static func isConnectionFailure(_ error: Error) -> Bool {
        let urlError = error as? URLError
            ?? (error as NSError).userInfo[NSUnderlyingErrorKey] as? URLError
        if let urlError {
            switch urlError.code {
            case .cannotConnectToHost, .networkConnectionLost, .timedOut,
                 .notConnectedToInternet, .cannotFindHost:
                return true
            default:
                break
            }
        }
        let ns = error as NSError
        return ns.domain == NSURLErrorDomain && [
            NSURLErrorCannotConnectToHost,
            NSURLErrorNetworkConnectionLost,
            NSURLErrorTimedOut,
            NSURLErrorNotConnectedToInternet,
            NSURLErrorCannotFindHost,
        ].contains(ns.code)
    }

    static func userMessage(
        for error: Error,
        fallback: String = "无法连接到 AI 引擎，请重试。"
    ) -> String {
        if isConnectionFailure(error) {
            return fallback
        }
        return error.localizedDescription
    }
}
