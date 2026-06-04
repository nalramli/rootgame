import { useContext } from "react";
import { ClearingContext } from "./Clearing";
import { factionToColor } from "../../utils/factionColors";
import { type FactionLabel } from "../../utils/factionUtils";
import { Tooltip } from "@mantine/core";

export type BuildingType =
  | "roosts"
  | "sawmills"
  | "workshops"
  | "recruiters"
  | "base"
  | "ruin"
  | "citadels"
  | "markets"
  | "strongholds";

export type BuildingInfo = {
  buildingType: BuildingType;
  faction: FactionLabel;
};

export const BuildingSlot = ({
  x,
  y,
  size,
  buildingInfo = null,
  tooltip,
}: {
  x: number;
  y: number;
  size: number;
  buildingInfo: BuildingInfo | null;
  tooltip?: string;
}) => {
  const ctx = useContext(ClearingContext);
  if (!ctx) throw new Error("Square must be nested inside Circle");
  const { cx, cy, r } = ctx;
  const absSize = size * r; // relative to radius
  const absX = cx + x * r - absSize / 2;
  const absY = cy + y * r - absSize / 2;
  let color = "none";
  let text = "";
  if (buildingInfo) {
    if (buildingInfo.buildingType === "ruin") {
      color = "#808080"; // Grey for ruins
      text = "R";
    } else {
      color = factionToColor(buildingInfo.faction);
      text = buildingInfo.buildingType[0];
    }
  }

  return (
    <Tooltip label={tooltip} disabled={!tooltip} openDelay={0} withArrow>
      <g>
        <rect
          x={absX}
          y={absY}
          width={absSize}
          height={absSize}
          stroke="black"
          fill={color}
        />
        <text
          x={absX + absSize / 2}
          y={absY + (3 * absSize) / 4}
          textAnchor="middle"
          stroke="white"
        >
          {text}
        </text>
      </g>
    </Tooltip>
  );
};
