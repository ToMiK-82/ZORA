/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'zora-bg': '#0C111D',
        'zora-card': '#131B2A',
        'zora-border': '#2A3A4E',
        'zora-text': '#FFFFFF',
        'zora-muted': '#A0B3CC',
        'zora-accent': '#FF8C42',
        'zora-accent-light': '#FFB347',
        'zora-green': '#22C55E',
        'zora-yellow': '#F59E0B',
        'zora-red': '#EF4444',
        'zora-gray': '#6B7280',
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
