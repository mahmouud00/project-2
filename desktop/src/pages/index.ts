import type { ComponentType } from "react";
import type { PageProps } from "../lib/title";
import Dashboard from "./Dashboard";
import Customers from "./Customers";
import Surveys from "./Surveys";
import Quotations from "./Quotations";
import Invoices from "./Invoices";
import WorkOrders from "./WorkOrders";
import Hr from "./Hr";
import Offcuts from "./Offcuts";
import Purchasing from "./Purchasing";
import Treasury from "./Treasury";
import Library from "./Library";
import Users from "./Users";
import Settings from "./Settings";
import System from "./System";
import FieldPage from "./Field";

export const PAGES: Record<string, ComponentType<PageProps>> = {
  dashboard: Dashboard,
  customers: Customers,
  surveys: Surveys,
  quotations: Quotations,
  invoices: Invoices,
  "work-orders": WorkOrders,
  hr: Hr,
  offcuts: Offcuts,
  purchasing: Purchasing,
  treasury: Treasury,
  library: Library,
  users: Users,
  settings: Settings,
  system: System,
  field: FieldPage,
};
