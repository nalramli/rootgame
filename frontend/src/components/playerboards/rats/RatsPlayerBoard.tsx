import { Modal, Stack, Paper, LoadingOverlay, Grid } from "@mantine/core";
import { useContext } from "react";
import { GameContext } from "../../../contexts/GameProvider";
import useRatsPlayerQuery from "../../../hooks/useRatsPlayerQuery";
import RatsHeaderSection from "./RatsHeaderSection";
import RatsTurnFlow from "./RatsTurnFlow";
import RatsHoardSection from "./RatsHoardSection";

interface RatsPlayerBoardProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function RatsPlayerBoard({
  isOpen,
  onClose,
}: RatsPlayerBoardProps) {
  const { gameId } = useContext(GameContext);
  const { publicInfo, isLoading } = useRatsPlayerQuery(gameId, isOpen);

  const warriorsInSupply =
    publicInfo?.warriors.filter((w) => w.clearing_number === null).length ?? 0;
  const mobsInSupply =
    publicInfo?.tokens.mob.filter((m) => m.token.clearing_number === null).length ?? 0;
  const strongholdsInSupply =
    publicInfo?.buildings.strongholds.filter((s) => s.building.clearing_number === null).length ?? 0;

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      size="90%"
      centered
      padding={0}
      withCloseButton={false}
      styles={{ content: { background: "transparent", boxShadow: "none" } }}
      overlayProps={{
        backgroundOpacity: 0.55,
        blur: 3,
      }}
    >
      <Paper
        p="md"
        radius="lg"
        shadow="xl"
        style={{
          backgroundColor: "#f5ead6",
          border: "4px solid #8B0000",
          overflow: "hidden",
          position: "relative",
        }}
      >
        <LoadingOverlay visible={isLoading} overlayProps={{ blur: 2 }} />
        {publicInfo && (
          <Stack gap="md">
            <RatsHeaderSection
              warriorsInSupply={warriorsInSupply}
              mobsInSupply={mobsInSupply}
              strongholdsInSupply={strongholdsInSupply}
            />

            <Grid gutter="md" align="stretch">
              {/* Left Column: Turn Flow */}
              <Grid.Col span={{ base: 12, md: 5 }}>
                <Paper
                  withBorder
                  p="xs"
                  radius="md"
                  bg="white"
                  shadow="sm"
                  style={{ flex: 1 }}
                >
                  <RatsTurnFlow />
                </Paper>
              </Grid.Col>

              {/* Right Column: Hoard */}
              <Grid.Col span={{ base: 12, md: 7 }}>
                <RatsHoardSection
                  commandItems={publicInfo.command_items}
                  prowessItems={publicInfo.prowess_items}
                  mood={publicInfo.mood}
                  validMoods={publicInfo.valid_moods}
                />
              </Grid.Col>
            </Grid>
          </Stack>
        )}
      </Paper>
    </Modal>
  );
}
