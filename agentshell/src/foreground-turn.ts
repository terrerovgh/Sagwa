/** Keep delayed events from an older task out of the current device turn. */
export class ForegroundTurn {
  private task:string|null=null;
  private speechAfter=0;
  select(task:string|null){this.task=task;}
  recover(task:string|null,sequence:number){
    if(!Number.isSafeInteger(sequence)||sequence<0)throw Error('invalid_sequence');
    this.task=task;this.speechAfter=Math.max(this.speechAfter,sequence);
  }
  accepts(task:string|null){return !task||this.task===task;}
  acceptsSpeech(task:string|null,sequence:number){
    return !!task&&this.task===task&&Number.isSafeInteger(sequence)&&sequence>this.speechAfter;
  }
  selected(task:string){return this.task===task;}
}
