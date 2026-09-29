import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0C1027",
        panel: "#131938",
        raise: "#1B2247",
        edge: "#2B3468",
        soft: "#E7EAFF",
        mute: "#8F98CC",
        volt: "#8577FF",
        amber: "#FFB224",
        mint: "#3FE0A0",
        coral: "#FF5F7A",
      },
      fontFamily: {
        display: ["var(--font-sora)", "system-ui", "sans-serif"],
        mono: ["var(--font-jb)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
