import { useTheme } from "../lib/theme";

/** The Comp11 Labs mark, with a light-on-dark version for the dark theme. */
export function Logo({ height = 30 }: { height?: number }) {
  const { resolved } = useTheme();
  return (
    <img src={resolved === "dark" ? "/brand/comp11-logo-dark.png" : "/brand/comp11-logo.png"}
      alt="Comp11 Labs" height={height} style={{ height, width: "auto" }} />
  );
}
