using Lumina.Services;

namespace Lumina.Features.Settings;

/// Validates a simplified custom OpenAI-compatible resource before PUT /settings.
public static class CustomResourceDraft
{
    public static readonly string[] BuiltInIds = ["ollama", "openai", "openrouter", "cursor"];

    public static string? Validate(string? id, string? baseUrl, string? model, IEnumerable<string>? existingIds = null)
    {
        var trimmedId = id?.Trim() ?? "";
        if (trimmedId.Length == 0) return "请填写资源 id";
        if (trimmedId.Contains(' ') || trimmedId.Contains(',')) return "资源 id 不能含空格或逗号";
        if (BuiltInIds.Contains(trimmedId, StringComparer.OrdinalIgnoreCase))
            return "内置资源请用上方表单编辑";
        if (existingIds is not null
            && existingIds.Any(x => string.Equals(x, trimmedId, StringComparison.OrdinalIgnoreCase)))
        {
            return "该资源 id 已存在";
        }
        if (string.IsNullOrWhiteSpace(baseUrl)) return "请填写 Base URL";
        if (!Uri.TryCreate(baseUrl.Trim(), UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
        {
            return "Base URL 无效";
        }
        if (string.IsNullOrWhiteSpace(model)) return "请填写模型名";
        return null;
    }

    public static bool IsBuiltIn(string? id) =>
        !string.IsNullOrWhiteSpace(id)
        && BuiltInIds.Contains(id.Trim(), StringComparer.OrdinalIgnoreCase);

    public static bool CanDelete(string? id) =>
        !string.IsNullOrWhiteSpace(id) && !IsBuiltIn(id);

    public static void RemoveFromPriority(List<string> priority, string id) =>
        priority.RemoveAll(x => string.Equals(x, id, StringComparison.OrdinalIgnoreCase));

    public static void Detach(
        List<ModelResourceSettings> resources,
        List<string> chatPriority,
        List<string> summarizePriority,
        string id)
    {
        if (!CanDelete(id)) return;
        resources.RemoveAll(r => string.Equals(r.Id, id, StringComparison.OrdinalIgnoreCase));
        RemoveFromPriority(chatPriority, id);
        RemoveFromPriority(summarizePriority, id);
    }

    public static ModelResourceSettings Build(
        string id,
        string baseUrl,
        string model,
        string? advancedModel,
        string? apiKey)
    {
        return new ModelResourceSettings
        {
            Id = id.Trim(),
            Provider = "openai",
            BaseUrl = baseUrl.Trim(),
            Model = model.Trim(),
            AdvancedModel = string.IsNullOrWhiteSpace(advancedModel) ? null : advancedModel.Trim(),
            ApiKey = string.IsNullOrWhiteSpace(apiKey) ? null : apiKey.Trim(),
        };
    }
}
