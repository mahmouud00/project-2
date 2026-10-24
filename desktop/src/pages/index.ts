import type { ComponentType } from "react";
import type { PageProps } from "../lib/title";
import Dashboard from "./Dashboard";
import Customers from "./Customers";
import Surveys from "./Surveys";
import Quotations from "./Quotations";
import Invoices from "./Invoices";
import WorkOrders from "./WorkOrders";
import Inventory from "./Inventory";
import Purchasing from "./Purchasing";
import Treasury from "./Treasury";
import Library from "./Library";
import PriceLists from "./PriceLists";
import Users from "./Users";
import Settings from "./Settings";
import System from "./System";

export const PAGES: Record<string, ComponentType<PageProps>> = {
  dashboard: Dashboard,
  customers: Customers,
  surveys: Surveys,
  quotations: Quotations,
  invoices: Invoices,
  "work-orders": WorkOrders,
  inventory: Inventory,
  purchasing: Purchasing,
  treasury: Treasury,
  library: Library,
  "price-lists": PriceLists,
  users: Users,
  settings: Settings,
  system: System,
};
