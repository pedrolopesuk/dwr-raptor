"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
} from "@carbon/react";

import { Section } from "@/components/Section";

import { formatScalar, shortHash } from "@/lib/format";
import type { ModelCapabilities, ModelSchema } from "@/lib/types";

export function ModelPanel({
  schema,
  modelHash,
  capabilities,
}: {
  schema: ModelSchema;
  modelHash: string | null;
  capabilities?: ModelCapabilities | null;
}) {
  return (
    <Section
      id="model-heading"
      title="Model"
      description={
        <>
          <strong className="drw-mono">{schema.model_id}</strong> v{schema.version} ·{" "}
          {schema.runtime} · hash <span className="drw-mono">{shortHash(modelHash)}</span>
        </>
      }
    >
      <div className="drw-stack">
        <p>{schema.description}</p>

        <TableContainer
          title="Parameters"
          description="Declared inputs, initial conditions (role = state) and controls. Values, units and bounds come from the model's authoritative schema; they are not inferred."
        >
          <Table aria-label="Model parameters" size="md" useZebraStyles>
            <TableHead>
              <TableRow>
                <TableHeader>name</TableHeader>
                <TableHeader>type</TableHeader>
                <TableHeader>role</TableHeader>
                <TableHeader>unit</TableHeader>
                <TableHeader className="drw-num">nominal</TableHeader>
                <TableHeader className="drw-num">lower</TableHeader>
                <TableHeader className="drw-num">upper</TableHeader>
                <TableHeader>description</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {schema.parameters.map((param) => (
                <TableRow key={param.name}>
                  <TableCell className="drw-mono">{param.name}</TableCell>
                  <TableCell>{param.type}</TableCell>
                  <TableCell>
                    <Tag type={param.role === "state" ? "teal" : "cool-gray"} size="sm">
                      {param.role}
                    </Tag>
                  </TableCell>
                  <TableCell>{param.unit}</TableCell>
                  <TableCell className="drw-num">{formatScalar(param.nominal)}</TableCell>
                  <TableCell className="drw-num">
                    {param.lower === null ? "—" : formatScalar(param.lower)}
                  </TableCell>
                  <TableCell className="drw-num">
                    {param.upper === null ? "—" : formatScalar(param.upper)}
                  </TableCell>
                  <TableCell>{param.description || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        <TableContainer title="Outputs">
          <Table aria-label="Model outputs" size="md">
            <TableHead>
              <TableRow>
                <TableHeader>name</TableHeader>
                <TableHeader>kind</TableHeader>
                <TableHeader>unit</TableHeader>
                <TableHeader>description</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {schema.outputs.map((output) => (
                <TableRow key={output.name}>
                  <TableCell className="drw-mono">{output.name}</TableCell>
                  <TableCell>{output.kind}</TableCell>
                  <TableCell>{output.unit}</TableCell>
                  <TableCell>{output.description || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        {capabilities ? (
          <div className="drw-stack-tight">
            <h3 className="drw-subheading">What this model supports</h3>
            <p className="drw-hint">
              Technical eligibility only: it describes what the engine can vary, sample and compare
              for this model. It is <strong>not</strong> a claim that any configuration is
              scientifically meaningful.
            </p>
            <dl className="drw-kv">
              <div>
                <dt>Factorable parameters</dt>
                <dd className="drw-mono" data-testid="cap-factorable">
                  {capabilities.factorable_parameters.map((parameter) => parameter.name).join(", ") ||
                    "none"}
                </dd>
              </div>
              <div>
                <dt>Outputs</dt>
                <dd className="drw-mono" data-testid="cap-outputs">
                  {[...capabilities.timeseries_outputs, ...capabilities.scalar_outputs].join(", ") ||
                    "none"}
                </dd>
              </div>
              <div>
                <dt>Sensitivity</dt>
                <dd data-testid="cap-sensitivity">{capabilities.sensitivity ?? "unavailable"}</dd>
              </div>
            </dl>
            {capabilities.limitations.length > 0 ? (
              <div>
                <h4 className="drw-subheading">Limitations</h4>
                <ul className="drw-stack-tight" data-testid="cap-limitations">
                  {capabilities.limitations.map((limitation) => (
                    <li key={limitation} className="drw-hint">
                      {limitation}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </Section>
  );
}
