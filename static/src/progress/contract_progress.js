/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { formatMonetary } from "@web/views/fields/formatters";

export class BiotexContractProgress extends Component {
    static template = "biotex_contract.Progress";
    static props = { ...standardFieldProps };

    get data() {
        return this.props.record.data[this.props.name] || { lines: [] };
    }
    fmt(v) {
        return `${this.data.currency || ""} ${formatMonetary(v || 0, { digits: [16, 2] })}`;
    }
    get barClass() {
        const p = this.data.progress || 0;
        if (p >= 100) return "bg-danger";
        if (p >= (this.data.alert_pct || 85)) return "bg-warning";
        return "bg-success";
    }
    get invoicedPct() {
        return this.data.amount_total ? Math.min(100, (this.data.amount_invoiced / this.data.amount_total) * 100) : 0;
    }
    lineClass(l) {
        if (l.progress >= 100) return "table-success";
        if (l.progress > 0) return "table-warning";
        return "";
    }
}

registry.category("fields").add("biotex_contract_progress", {
    component: BiotexContractProgress,
    supportedTypes: ["json"],
});
