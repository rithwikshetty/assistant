import type { components, operations } from "./openapi";

export type ApiSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];
export type ApiOperation<Name extends keyof operations> = operations[Name];
