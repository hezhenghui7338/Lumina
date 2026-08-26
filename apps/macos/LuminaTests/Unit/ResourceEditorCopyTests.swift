import XCTest
@testable import Lumina

final class ResourceEditorCopyTests: XCTestCase {
    func testResourceEditorCopy_keepsLabelsShort() {
        XCTAssertFalse(ResourceEditorCopy.formLabels.isEmpty)
        for label in ResourceEditorCopy.formLabels {
            for fragment in ResourceEditorCopy.labelForbiddenFragments {
                XCTAssertFalse(
                    label.contains(fragment),
                    "Form label “\(label)” must not contain “\(fragment)”; put examples in placeholder/footer"
                )
            }
            XCTAssertLessThanOrEqual(label.count, 8, "Form label “\(label)” is too long for a caption")
        }
        XCTAssertEqual(ResourceEditorCopy.normalModelLabel, "正常模型")
        XCTAssertEqual(ResourceEditorCopy.advancedModelLabel, "高级模型")
        XCTAssertEqual(ResourceEditorCopy.typeLabel, "类型")
    }

    func testResourceEditorCopy_doesNotConcatenatePlaceholderIntoLabel() {
        for kind in ModelProviderKind.allCases {
            XCTAssertNotEqual(
                "正常\(kind.modelPlaceholder)",
                ResourceEditorCopy.normalModelLabel,
                "\(kind.label) still stuffing modelPlaceholder into the Form label"
            )
            XCTAssertFalse(
                ResourceEditorCopy.normalModelLabel.contains(kind.editorModelPlaceholder)
            )
        }
    }

    func testResourceEditorCopy_placeholdersAndFootersCarryExamples() {
        XCTAssertEqual(ResourceEditorCopy.advancedModelPlaceholder, "留空则使用正常模型")
        XCTAssertTrue(ResourceEditorCopy.advancedModelPlaceholder.contains("留空"))

        XCTAssertEqual(ModelProviderKind.ollama.editorModelPlaceholder, "如 qwen3.5:4b")
        XCTAssertTrue(ModelProviderKind.openai.editorModelPlaceholder.contains("如"))

        let openrouterFooter = ModelProviderKind.openrouter.editorConnectionFooter
        XCTAssertNotNil(openrouterFooter)
        XCTAssertTrue(openrouterFooter?.contains("试用") == true)
        XCTAssertNil(ModelProviderKind.ollama.editorConnectionFooter)
    }

    func testResourceEditorSheet_usesVerticalFieldsAndReadableBlocks() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let sheet = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Settings/ResourceEditorSheet.swift"),
            encoding: .utf8
        )
        XCTAssertFalse(
            sheet.contains("正常\\(kind.modelPlaceholder)"),
            "must not stuff modelPlaceholder into the Form label column"
        )
        XCTAssertFalse(sheet.contains("LabeledContent(\"状态\""))
        XCTAssertFalse(sheet.contains("minWidth: 420"))
        XCTAssertTrue(sheet.contains("minWidth: 520"))
        XCTAssertTrue(sheet.contains("ResourceFormField"))
        XCTAssertTrue(sheet.contains("ResourceReadableBlock"))
        XCTAssertTrue(sheet.contains("editorModelPlaceholder"))
        XCTAssertTrue(sheet.contains(".textSelection(.enabled)"))
        XCTAssertTrue(sheet.contains(".multilineTextAlignment(.leading)"))
    }
}
