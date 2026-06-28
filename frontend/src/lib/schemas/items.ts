/** Mirrors backend `schemas/items.py`. Keep in sync with the Pydantic models. */

export interface Item {
  id: string;
  name: string;
  description: string | null;
  owner_id: string;
  created_at: string;
  updated_at: string;
}

export interface ItemCreate {
  name: string;
  description?: string | null;
}

export interface ItemUpdate {
  name?: string | null;
  description?: string | null;
}
