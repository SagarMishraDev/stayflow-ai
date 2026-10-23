/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // View 2 design system (approved 2026-10-23): navy/teal sidebar,
        // cool-gray app background, white cards, teal/emerald data viz.
        // Token NAMES are unchanged from the previous theme so every
        // page inherits the new palette without a rewrite.
        paper: "#F4F7FA", // app background
        surface: "#F8FAFC", // secondary surface
        ink: {
          DEFAULT: "#102A43", // primary text
          soft: "#52677D", // secondary text
          muted: "#8293A5", // muted text
        },
        sun: {
          DEFAULT: "#FBBF24", // amber accent (zero-booking, warnings)
          hover: "#F59E0B",
        },
        coral: {
          DEFAULT: "#EF4444", // danger
          soft: "#FDECEC", // danger badge + alert backgrounds
          deep: "#C22F2F", // danger text / solid danger (readable on white)
        },
        teal: "#0F9D94", // primary brand teal
        "dark-teal": "#087E78",
        "deep-teal": "#075E5A", // primary actions, links
        "bright-teal": "#18B8AC",
        sidebar: {
          DEFAULT: "#062F33", // sidebar gradient start
          deep: "#041F25", // sidebar gradient end
          active: "#0A6665", // active nav item
        },
        emerald: "#10B981", // success
        pale: "#E7F7F4", // pale teal surface / icon chips
        warn: "#F59E0B",
        info: "#3B82F6",
        grape: "#8B5CF6",
        compare: "#B8CDD3", // comparison series
        gridline: "#E7EDF2",
        mist: "#F8FAFC", // soft panels (== secondary surface)
        line: "#E6ECF1", // standard border
        divider: "#EDF1F5",
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        display: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16, 42, 67, 0.05), 0 4px 16px rgba(16, 42, 67, 0.05)",
        lift: "0 4px 8px rgba(16, 42, 67, 0.06), 0 12px 28px rgba(16, 42, 67, 0.10)",
      },
    },
  },
  plugins: [],
};
