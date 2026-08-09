using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

namespace Lumina.Services;

/// <summary>Incremental SSE line reader for chat / book events.</summary>
public static class SseReader
{
    public static async IAsyncEnumerable<JsonElement> ReadDataEventsAsync(
        Stream stream,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        using var reader = new StreamReader(stream, Encoding.UTF8);
        while (!cancellationToken.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
            if (line is null) yield break;
            if (!line.StartsWith("data: ", StringComparison.Ordinal)) continue;
            var json = line["data: ".Length..];
            if (string.IsNullOrWhiteSpace(json)) continue;
            JsonElement el;
            try
            {
                using var doc = JsonDocument.Parse(json);
                el = doc.RootElement.Clone();
            }
            catch (JsonException)
            {
                continue;
            }
            yield return el;
        }
    }
}
