/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Landing-page design language (see frontend/landing/styles.css):
        // paper / ink / sun / coral / teal / deep-teal / mist.
        paper: "#FFFFFF", // page background, card surfaces
        ink: {
          DEFAULT: "#2B2B2B", // text
          soft: "#5C5C5C", // secondary text
        },
        sun: {
          DEFAULT: "#FFD23F", // the one bold accent — always with ink text
          hover: "#F5C61F",
        },
        coral: {
          DEFAULT: "#FF6B6B", // danger accents / borders
          soft: "#FFE9E9", // danger badge + alert backgrounds
          deep: "#C22F2F", // danger text / solid danger (readable on white)
        },
        teal: "#1BA39C", // interactive accents, focus, success borders
        "deep-teal": "#08756F", // sidebar, primary actions, links
        mist: "#EFF8F6", // panels, soft fills, hover states
        line: "#DBDBDB", // borders / dividers (landing --line: hsl(0 0% 86%))
      },
      fontFamily: {
        sans: ["Nunito Sans", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ["Barlow Condensed", "Arial Narrow", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        card: "0 10px 30px rgba(43, 43, 43, 0.08)",
        lift: "0 18px 40px rgba(43, 43, 43, 0.14)",
      },
    },
  },
  plugins: [],
};
