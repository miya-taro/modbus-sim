import { describe, expect, it } from "vitest";
import {
  formatDecodedDisplay,
  parseDecodedInput,
  parseRawInput,
  validateAddress,
} from "./datatype";

describe("formatDecodedDisplay", () => {
  it("uint16", () => {
    expect(formatDecodedDisplay("uint16", "hr", 4660)).toBe("0x1234");
    expect(formatDecodedDisplay("uint16", "hr", 0)).toBe("0x0000");
    expect(formatDecodedDisplay("uint16", "hr", 65535)).toBe("0xFFFF");
  });
  it("int16 negative uses memory repr", () => {
    expect(formatDecodedDisplay("int16", "hr", 0xffff)).toBe("0xFFFF");
  });
  it("int32", () => {
    expect(formatDecodedDisplay("int32", "hr", -1)).toBe("0xFFFFFFFF");
    expect(formatDecodedDisplay("int32", "hr", 0x12345678)).toBe("0x12345678");
  });
  it("float32 bit pattern", () => {
    expect(formatDecodedDisplay("float32", "hr", 1)).toBe("0x3F800000");
  });
  it("float64 bit pattern (pi)", () => {
    expect(formatDecodedDisplay("float64", "hr", Math.PI)).toBe("0x400921FB54442D18");
  });
  it("coil", () => {
    expect(formatDecodedDisplay("bool", "coil", 1)).toBe("0x01");
    expect(formatDecodedDisplay("bool", "coil", 0)).toBe("0x00");
  });
});

describe("parseDecodedInput", () => {
  it("accepts 0x / bare / trailing h as hex", () => {
    expect(parseDecodedInput("0x1234", "uint16")).toBe(4660);
    expect(parseDecodedInput("1234", "uint16")).toBe(4660);
    expect(parseDecodedInput("1234h", "uint16")).toBe(4660);
  });
  it("int16 FFFF -> memory repr 0xFFFF", () => {
    expect(parseDecodedInput("0xFFFF", "int16")).toBe(0xffff);
  });
  it("int32 FFFFFFFF -> -1", () => {
    expect(parseDecodedInput("FFFFFFFF", "int32")).toBe(-1);
    expect(parseDecodedInput("EDCBA988", "int32")).toBe(-0x12345678);
  });
  it("float32 round trips through bit pattern", () => {
    expect(parseDecodedInput("0x3F800000", "float32")).toBe(1);
  });
  it("float64 round trips (pi)", () => {
    expect(parseDecodedInput("0x400921FB54442D18", "float64")).toBeCloseTo(Math.PI, 12);
  });
});

describe("parseRawInput", () => {
  it("integers only for non-float", () => {
    expect(parseRawInput("42", "uint16")).toBe(42);
    expect(() => parseRawInput("1.5", "uint16")).toThrow();
  });
  it("floats accept decimals", () => {
    expect(parseRawInput("2.5", "float64")).toBe(2.5);
  });
});

describe("word order", () => {
  it("ABCD is the default and matches big-endian", () => {
    expect(formatDecodedDisplay("int32", "hr", 0x12345678, "ABCD")).toBe("0x12345678");
  });
  it("CDAB swaps 16-bit words", () => {
    expect(formatDecodedDisplay("int32", "hr", 0x12345678, "CDAB")).toBe("0x56781234");
  });
  it("BADC swaps bytes within each word", () => {
    expect(formatDecodedDisplay("int32", "hr", 0x12345678, "BADC")).toBe("0x34127856");
  });
  it("DCBA fully reverses", () => {
    expect(formatDecodedDisplay("int32", "hr", 0x12345678, "DCBA")).toBe("0x78563412");
  });
  it("round-trips through decoded input for every order", () => {
    for (const order of ["ABCD", "CDAB", "BADC", "DCBA"] as const) {
      const hex = formatDecodedDisplay("float32", "hr", 3.5, order);
      expect(parseDecodedInput(hex, "float32", order)).toBeCloseTo(3.5, 5);
      const hex64 = formatDecodedDisplay("float64", "hr", -12345.678, order);
      expect(parseDecodedInput(hex64, "float64", order)).toBeCloseTo(-12345.678, 6);
    }
  });
});

describe("validateAddress", () => {
  it("rejects out of range", () => {
    expect(() => validateAddress(-1, "uint16")).toThrow();
    expect(() => validateAddress(65536, "uint16")).toThrow();
  });
  it("uint16 allows the top address", () => {
    expect(() => validateAddress(65535, "uint16")).not.toThrow();
  });
  it("int32 must be <= 65534", () => {
    expect(() => validateAddress(65535, "int32")).toThrow();
    expect(() => validateAddress(65534, "int32")).not.toThrow();
  });
  it("float64 must be <= 65532", () => {
    expect(() => validateAddress(65533, "float64")).toThrow();
    expect(() => validateAddress(65532, "float64")).not.toThrow();
  });
});
