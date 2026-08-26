namespace Lumina.Features.Library;

/// Navigation extras for the library page. Avoids re-importing on every visit.
public sealed record LibraryNavArgs(bool OpenImport = false);
