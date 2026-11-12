import { gexApi, unwrap } from "../../api/client";
import { useResource } from "../../lib/useResource";

export const useUnderlyings = () => useResource(() => unwrap(gexApi.GET("/underlyings")));
