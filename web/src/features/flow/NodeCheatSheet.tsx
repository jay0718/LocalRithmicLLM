import { useStoredState } from "../../lib/useStoredState";

type Row = { where: string; blue: string; red: string };

const RISING: Row[] = [
  {
    where: "위에 있음",
    blue: "저항. 다가가며 속도가 줄면 추격 금지·익절 고려. 뚫고 위에서 버티면 다음 노드까지.",
    red: "닿으면 가속하기 쉬움. 돌파가 확인되면 추세 추종, 막히면 급반락 주의.",
  },
  {
    where: "아래에 있음",
    blue: "눌림 지지 후보. 되돌림에서 멈추는지 보고 매수 관찰.",
    red: "다시 내려오면 그 아래로 빨라질 수 있음. 손절 기준선.",
  },
];

const FALLING: Row[] = [
  {
    where: "아래에 있음",
    blue: "지지. 다가가며 속도가 줄면 숏 익절·반등 관찰.",
    red: "뚫으면 가속 하락. 이탈이 확인되면 추세 추종.",
  },
  {
    where: "위에 있음",
    blue: "반등 저항. 반등이 여기서 막히는지 확인.",
    red: "되돌아 올라오면 급반등(숏 커버) 가능. 숏 손절 기준선.",
  },
];

function Table({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <table className="cheat-table">
      <caption>{title}</caption>
      <thead>
        <tr>
          <th scope="col">노드 위치</th>
          <th scope="col">
            <span className="guide-swatch guide-positive" /> 파랑 (+)
          </th>
          <th scope="col">
            <span className="guide-swatch guide-negative" /> 빨강 (−)
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.where}>
            <th scope="row">{row.where}</th>
            <td>{row.blue}</td>
            <td>{row.red}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A short Korean cheat sheet under the node table: how each node colour is usually read, by case. */
export function NodeCheatSheet() {
  const [open, setOpen] = useStoredState("lrl.flow.cheatSheetOpen", true);
  return (
    <details
      className="cheat-sheet"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>노드 치트시트</summary>
      <ul className="cheat-basics">
        <li>
          <b>파랑(+)</b> 딜러 롱감마: 가격 움직임을 반대로 받아냄 → 느려지고 멈추거나 붙음(벽·자석).
        </li>
        <li>
          <b>빨강(−)</b> 딜러 숏감마: 움직임을 따라감 → 뚫으면 빨라짐(가속 구간).
        </li>
        <li>
          <b>킹 ★</b> 가장 큰 노드, 오늘 가장 중요한 가격. 파란 킹은 핀(특히 장 후반), 빨간 킹은 그 주변
          휩쏘와 큰 움직임.
        </li>
        <li>2등이 킹의 80% 이상으로 따라오거나 킹이 바뀌면 주도 가격이 옮겨가는 중.</li>
      </ul>
      <Table title="상승 중일 때" rows={RISING} />
      <Table title="하락 중일 때" rows={FALLING} />
      <ul className="cheat-basics">
        <li>감마 플립 위는 잔잔·되돌림, 아래는 추세·변동성이 커지기 쉬움.</li>
        <li>0DTE라 오후로 갈수록 값도 영향도 커짐. 오전 노드는 약하게 보기.</li>
        <li>노드는 추정치예요. 가격 반응을 확인하고 들어가고, 손절은 반대편 노드 너머에.</li>
      </ul>
    </details>
  );
}
