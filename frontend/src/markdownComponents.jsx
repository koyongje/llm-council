// Shared ReactMarkdown overrides: open every link (e.g. cited sources) in a new tab.
export const markdownComponents = {
  a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};
