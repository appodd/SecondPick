import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { imageSource, ProductGallery, ProductImage } from "./ProductImages";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it("rejects unsafe or credential-bearing image URLs", () => {
  expect(imageSource("javascript:alert(1)")).toBeUndefined();
  expect(imageSource("file:///private/image.jpg")).toBeUndefined();
  expect(imageSource("https://user:password@example.test/img")).toBeUndefined();
  expect(imageSource("https://example.test/img.jpg")).toBe("https://example.test/img.jpg");
});
it("uses one missing/failed placeholder and retries when a product source changes", () => {
  const { rerender } = render(<ProductImage title="商品 A" />);
  expect(screen.getByRole("img", { name: /暂无商品图片/ })).toBeVisible();
  rerender(<ProductImage title="商品 A" src="https://example.test/a.jpg" />);
  fireEvent.error(screen.getByRole("img", { name: "商品 A" }));
  expect(screen.getByRole("img", { name: /图片加载失败/ })).toBeVisible();
  rerender(<ProductImage title="商品 B" src="https://example.test/b.jpg" />);
  expect(screen.getByRole("img", { name: "商品 B" })).toHaveAttribute("loading", "lazy");
  expect(screen.getByRole("img", { name: "商品 B" })).toHaveAttribute("decoding", "async");
});
it("exposes only safe unique supplied images and distinguishes an incomplete gallery", () => {
  render(<ProductGallery title="测试商品" images={["https://example.test/one.jpg", "https://example.test/two.jpg", "https://example.test/one.jpg", "file:///private/photo"]} />);
  expect(screen.getByText("2 张可浏览")).toBeVisible();
  expect(screen.getByText(/完整图片列表尚未接入/)).toBeVisible();
  expect(screen.getAllByRole("button", { name: /预览第/ })).toHaveLength(2);
});
