import { request } from "@/lib/api/client";
import type { Item, ItemCreate, ItemUpdate } from "@/lib/schemas/items";

/** The typed items SDK — one function per backend `/items` endpoint. */

export function listItems(): Promise<Item[]> {
  return request<Item[]>("/items");
}

export function getItem(id: string): Promise<Item> {
  return request<Item>(`/items/${id}`);
}

export function createItem(payload: ItemCreate): Promise<Item> {
  return request<Item>("/items", { method: "POST", body: payload });
}

export function updateItem(id: string, payload: ItemUpdate): Promise<Item> {
  return request<Item>(`/items/${id}`, { method: "PUT", body: payload });
}

export function deleteItem(id: string): Promise<void> {
  return request<void>(`/items/${id}`, { method: "DELETE" });
}
