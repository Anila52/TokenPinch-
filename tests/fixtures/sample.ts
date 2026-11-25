import { helper as h } from "./helper";

export function helper(x: number): number {
  return x + 1;
}

export function target(n: number): number {
  return helper(n) * 2;
}

export class Box {
  method(n: number): number {
    return helper(n);
  }
}

export function unused(z: number): number {
  return z * 9;
}
