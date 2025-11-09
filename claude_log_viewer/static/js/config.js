// Configuration and constants

// Plan limits (hours per week)
export const planLimits = {
    pro: { sonnet: 80, opus: 0 },
    max5x: { sonnet: 280, opus: 35 },
    max20x: { sonnet: 480, opus: 40 }
};

// Color palette for sessions
export const colorPalette = [
    '#1a7f37', '#0969da', '#bf8700', '#8250df', '#cf222e',
    '#1f6feb', '#d29922', '#8957e5', '#ea4a5a', '#0969da',
    '#2da44e', '#1f883d', '#bc4c00', '#6639ba', '#d1242f'
];

// Initialize markdown-it with syntax highlighting
export const md = window.markdownit({
    html: true,
    linkify: true,
    typographer: true,
    highlight: function (str, lang) {
        if (lang && hljs.getLanguage(lang)) {
            try {
                return hljs.highlight(str, { language: lang }).value;
            } catch (__) {}
        }
        return '';
    }
});
