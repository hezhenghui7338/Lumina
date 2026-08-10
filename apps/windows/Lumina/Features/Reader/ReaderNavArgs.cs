namespace Lumina.Features.Reader;

public sealed record ReaderNavArgs(string BookId, string Title, int? SegmentIndex = null);
