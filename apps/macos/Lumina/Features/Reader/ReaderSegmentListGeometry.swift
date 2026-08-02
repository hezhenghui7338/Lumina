import CoreGraphics

enum ReaderSegmentListGeometry {
    static func isPointerInSegmentList(_ point: CGPoint, segmentsWidth: CGFloat) -> Bool {
        point.x <= segmentsWidth
    }
}

enum ReaderSegmentPanelHeight {
    static let minHeight: CGFloat = 160
    static let maxHeight: CGFloat = 420

    static func clamp(_ height: CGFloat) -> CGFloat {
        min(max(height, minHeight), maxHeight)
    }

    /// Boxed source viewport: prefer the larger of locked and capped measured height
    /// so a stale low lock does not shrink the panel below the last summary measurement.
    static func boxedViewportHeight(measured: CGFloat, locked: CGFloat?) -> CGFloat {
        let cappedMeasured = clamp(measured)
        guard let locked else { return cappedMeasured }
        return max(locked, cappedMeasured)
    }
}
