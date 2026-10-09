/**
 * Console text is plain English (the residents' page /v/:id is the only bilingual screen).
 * `defineMessages` groups a page's strings; `msgFn<P>` types a string that takes parameters.
 */

export function defineMessages<T extends Record<string, string | ((p: never) => string)>>(messages: T): T {
  return messages;
}

export function msgFn<P>(fn: (p: P) => string): (p: P) => string {
  return fn;
}
