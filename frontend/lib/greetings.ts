
/**
 * Pool of greetings shown on the start page.
 * A random one is picked on each page load / refresh.
 *
 * `template` is a string with `{name}` as a placeholder for the user's first name.
 * The `{name}` token can appear anywhere in the sentence.
 */

export type Greeting = {
  template: string;
};

export const greetings: Greeting[] = [
  { template: "What are we tackling today, {name}?" },
  { template: "At your service, {name}" },
  { template: "Fire away, {name}" },
  { template: "{name}, what's the plan?" },
  { template: "{name}, let's make something happen!" },
  { template: "What's on your mind, {name}?" },
  { template: "Ready when you are, {name}" },
  { template: "{name}, let's dive in" },
  { template: "What can I help with, {name}?" },
  { template: "{name}, let's get to work" },
  { template: "What's next, {name}?" },
  { template: "How can I assist you today, {name}?" },
  { template: "{name}, what would you like to work on?" },
  { template: "What can we accomplish today, {name}?" },
  { template: "{name}, what would you like to explore?" },
  { template: "Let's make it a productive one, {name}!" },
  { template: "How can I help today, {name}?" },
  { template: "{name}, what's on the agenda?" },
  { template: "Good to see you, {name}" },
  { template: "{name}, ready to go?" },
];

/** Pick a random greeting from the pool. */
export function getRandomGreeting(): Greeting {
  return greetings[Math.floor(Math.random() * greetings.length)];
}

/**
 * Split a greeting template into segments around the `{name}` token.
 * Returns an array of `{ text, isName }` parts for rendering.
 */
export function parseGreeting(
  template: string,
  name: string,
): { text: string; isName: boolean }[] {
  const idx = template.indexOf("{name}");
  if (idx === -1) return [{ text: template, isName: false }];

  const parts: { text: string; isName: boolean }[] = [];
  const before = template.slice(0, idx);
  const after = template.slice(idx + "{name}".length);

  if (before) parts.push({ text: before, isName: false });
  parts.push({ text: name, isName: true });
  if (after) parts.push({ text: after, isName: false });

  return parts;
}
