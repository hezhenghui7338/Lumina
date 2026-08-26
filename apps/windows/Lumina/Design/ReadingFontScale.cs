namespace Lumina.Design;

/// Five reading size steps shared by the book reader and news preview.
public static class ReadingFontScale
{
    public static readonly double[] Steps = [0.85, 1.0, 1.15, 1.3, 1.45];
    public static readonly string[] Labels = ["较小", "标准", "较大", "大", "很大"];
    public const double BaseSize = 15;

    public static int NearestIndex(double scale)
    {
        var best = 0;
        var bestDelta = double.MaxValue;
        for (var i = 0; i < Steps.Length; i++)
        {
            var delta = Math.Abs(Steps[i] - scale);
            if (delta < bestDelta)
            {
                best = i;
                bestDelta = delta;
            }
        }
        return best;
    }

    public static double Snap(double scale) => Steps[NearestIndex(scale)];

    public static double Size(double scale) => BaseSize * Snap(scale);

    public static string Label(double scale)
    {
        var i = NearestIndex(scale);
        return Labels[i];
    }

    public static double Step(double current, int delta)
    {
        var i = Math.Clamp(NearestIndex(current) + delta, 0, Steps.Length - 1);
        return Steps[i];
    }

    public static bool CanDecrease(double scale) => NearestIndex(scale) > 0;

    public static bool CanIncrease(double scale) => NearestIndex(scale) < Steps.Length - 1;
}
