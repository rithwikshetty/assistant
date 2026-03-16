import type { Icon as IconComponent } from "@phosphor-icons/react";
import {
  Lightning,
  Sparkle,
  Fire,
  Globe,
  DiamondsFour,
  PuzzlePiece,
  Rocket,
  Lightbulb,
  Compass,
  Aperture,
  Leaf,
  Crown,
  DiceFive,
  Target,
  Hexagon,
  Graph,
  Anchor,
  Bone,
  Bug,
  Cake,
  OrangeSlice,
  CloudLightning,
  Clover,
  Cube,
  Cookie,
  Bread,
  Diamond,
  Metronome,
  Egg,
  Fan,
  Feather,
  Fingerprint,
  Fish,
  Flower,
  Ghost,
  Avocado,
  Heart,
  IceCream,
  GameController,
  Key,
  Lamp,
  MagnetStraight,
  Mountains,
  PaperPlaneTilt,
  TreePalm,
  PawPrint,
  Pizza,
  Rabbit,
  Rainbow,
  Sailboat,
  Spiral,
  Skull,
  Snowflake,
  Acorn,
  Sword,
  Tornado,
  Tree,
  Umbrella,
  Waves,
  Wind,
  Shrimp,
  Orange,
  Eyeglasses,
  MusicNotes,
  Planet,
  Palette,
  Pencil,
  Mouse,
  Boat,
  Knife,
  BowlFood,
  Tent,
} from "@phosphor-icons/react";

import type { SkillManifestFile } from "@/lib/api/skills";

export const SKILL_ICONS: IconComponent[] = [
  Lightning,
  Sparkle,
  Fire,
  Globe,
  DiamondsFour,
  PuzzlePiece,
  Rocket,
  Lightbulb,
  Compass,
  Aperture,
  Leaf,
  Crown,
  DiceFive,
  Target,
  Hexagon,
  Graph,
  Anchor,
  Bone,
  Bug,
  Cake,
  OrangeSlice,
  CloudLightning,
  Clover,
  Cube,
  Cookie,
  Bread,
  Diamond,
  Metronome,
  Egg,
  Fan,
  Feather,
  Fingerprint,
  Fish,
  Flower,
  Ghost,
  Avocado,
  Heart,
  IceCream,
  GameController,
  Key,
  Lamp,
  MagnetStraight,
  Mountains,
  PaperPlaneTilt,
  TreePalm,
  PawPrint,
  Pizza,
  Rabbit,
  Rainbow,
  Sailboat,
  Spiral,
  Skull,
  Snowflake,
  Acorn,
  Sword,
  Tornado,
  Tree,
  Umbrella,
  Waves,
  Wind,
  Shrimp,
  Orange,
  Eyeglasses,
  MusicNotes,
  Planet,
  Palette,
  Pencil,
  Mouse,
  Boat,
  Knife,
  BowlFood,
  Tent,
];

export const SKILL_COLORS = [
  { bg: "bg-rose-500/20", text: "text-rose-400" },
  { bg: "bg-amber-500/20", text: "text-amber-400" },
  { bg: "bg-emerald-500/20", text: "text-emerald-400" },
  { bg: "bg-teal-500/20", text: "text-teal-400" },
  { bg: "bg-stone-500/20", text: "text-stone-400" },
  { bg: "bg-cyan-500/20", text: "text-cyan-400" },
  { bg: "bg-pink-500/20", text: "text-pink-400" },
  { bg: "bg-orange-500/20", text: "text-orange-400" },
];

export function hashString(str: string) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function getSkillVisual(id: string) {
  const hash = hashString(id);
  return {
    Icon: SKILL_ICONS[hash % SKILL_ICONS.length],
    color: SKILL_COLORS[hash % SKILL_COLORS.length],
  };
}

export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return "-";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

export function groupFilesByFolder(files: SkillManifestFile[]) {
  const groups: { folder: string; files: SkillManifestFile[] }[] = [];
  const map = new Map<string, SkillManifestFile[]>();

  for (const file of files) {
    const slashIndex = file.path.lastIndexOf("/");
    const folder = slashIndex > 0 ? file.path.slice(0, slashIndex) : "";
    if (!map.has(folder)) {
      const arr: SkillManifestFile[] = [];
      map.set(folder, arr);
      groups.push({ folder, files: arr });
    }
    map.get(folder)!.push(file);
  }

  return groups;
}

