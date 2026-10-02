/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Front-desk console palette (see frontend/DESIGN.md)
        pine: {
          950: "#13322B", // deep pine — sidebar shell, primary buttons
          700: "#1F6B5C", // pine — links, focus, interactive accents
          100: "#DCE9E2",
          50: "#EFF6F1",
        },
        brass: {
          600: "#A97B24",
          500: "#C0902F", // brass — the one bold accent (arrivals/departures)
          100: "#F3E6C8",
        },
        paper: "#F5F1E8", // page background
        parchment: "#FDFCF9", // card/table surfaces
        ink: "#24292C", // text
        brick: {
          700: "#93302F",
          600: "#B23A3A", // danger / cancellations / sold-out
          100: "#F7DEDD",
        },
      },
      fontFamily: {
        sans: ["Archivo", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
