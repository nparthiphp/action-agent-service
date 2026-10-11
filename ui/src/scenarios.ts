import type { Recommendation } from "./types";

const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 5);

export interface Scenario { name: string; note: string; build: () => Recommendation }

export const SCENARIOS: Scenario[] = [
  { name: "Payments outage, production", note: "Open a ticket, scale the node group, update the ticket. Needs approval.",
    build: () => ({ recommendation_id: "ui-" + uid(), target: "payments", environment: "prod", confidence: 0.93,
      rationale: "Error rate above 5% with CPU saturated on the payments node group.", incident_ref: "INC-2041",
      steps: [
        { action_id: "create_ticket", params: { title: "Payments failing", severity: "high", service: "payments" } },
        { action_id: "scale_node_group", params: { group: "payments-ng", desired: 5 } },
        { action_id: "update_ticket", params: { ticket_id: "$step[0].ticket_id", note: "scaled payments-ng to 5" } },
      ] }) },
  { name: "Stop an idle dev VM", note: "FinOps saving in non-production. Reversible.",
    build: () => ({ recommendation_id: "ui-" + uid(), target: "vm-dev-01", environment: "nonprod", confidence: 0.88,
      rationale: "No CPU or network use for 14 days.", steps: [{ action_id: "stop_idle_resource", params: { resource_id: "vm-dev-01" } }] }) },
  { name: "Plan with a wrong target", note: "Scales a node group that does not exist. The dry run catches it before anything changes.",
    build: () => ({ recommendation_id: "ui-" + uid(), target: "payments", environment: "prod", confidence: 0.7,
      steps: [
        { action_id: "create_ticket", params: { title: "Scale test", severity: "low", service: "payments" } },
        { action_id: "scale_node_group", params: { group: "no-such-group", desired: 5 } },
      ] }) },
  { name: "Restart a service, production", note: "InfraOps restart. Production raises the tier.",
    build: () => ({ recommendation_id: "ui-" + uid(), target: "web-01", environment: "prod", confidence: 0.9,
      steps: [{ action_id: "restart_service", params: { host: "web-01", service: "payments" } }] }) },
];
